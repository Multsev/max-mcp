"""Download authenticated MAX files and inspect them without executing content."""
import asyncio
import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import py7zr
from mcp.server.fastmcp import Context, FastMCP
from py7zr.io import BytesIOFactory
from pypdf import PdfReader

from ..client import AppCtx
from ._common import positive_int

MAX_BYTES = 100 * 1024 * 1024


def root() -> Path:
    path = Path(os.environ.get("MAX_MCP_DOWNLOAD_ROOT", str(Path.home() / "Downloads/MAXAttachments"))).expanduser()
    if not path.is_absolute() or any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Download root must be absolute and contain no symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path.resolve()


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Invalid attachment URL")
    if not any(host == domain or host.endswith("." + domain) for domain in ("max.ru", "oneme.ru", "okcdn.ru", "mycdn.me")):
        raise ValueError("Attachment host is not an approved MAX CDN")


async def download(url: str, destination: Path, max_bytes: int) -> dict[str, Any]:
    validate_url(url)
    digest = hashlib.sha256()
    size = 0
    fd, temporary = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                for _ in range(6):
                    async with client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = str(response.url.join(response.headers["location"]))
                            validate_url(url)
                            continue
                        # Do not include signed URLs in errors or tool results.
                        if response.status_code != 200:
                            raise ValueError(f"Attachment download returned HTTP {response.status_code}")
                        if int(response.headers.get("content-length", "0")) > max_bytes:
                            raise ValueError("Attachment exceeds size limit")
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError("Attachment exceeds size limit")
                            output.write(chunk)
                            digest.update(chunk)
                        break
                else:
                    raise ValueError("Too many attachment redirects")
        os.link(temporary, destination)  # Atomic publication, never overwrite.
        return {"path": str(destination), "bytes": size, "sha256": digest.hexdigest()}
    except httpx.HTTPError:
        raise ValueError("Attachment network request failed") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def inspect(path: Path, max_chars: int, member: str | None = None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".zip", ".odt", ".docx"):
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 2000:
                raise ValueError("Archive has too many entries")
            if member is None:
                return {"members": [{"name": i.filename, "bytes": i.file_size} for i in infos]}
            info = archive.getinfo(member)
            if info.file_size > MAX_BYTES:
                raise ValueError("Archive member exceeds size limit")
            with archive.open(info) as stream:
                content = stream.read(max_chars * 4 + 1)
    elif suffix == ".7z":
        with py7zr.SevenZipFile(path) as archive:
            entries = archive.list()
            if len(entries) > 2000:
                raise ValueError("Archive has too many entries")
            if member is None:
                return {"members": [{"name": i.filename, "bytes": i.uncompressed} for i in entries]}
            if sum(i.uncompressed or 0 for i in entries) > MAX_BYTES:
                raise ValueError("Expanded archive exceeds size limit")
            if member not in [i.filename for i in entries]:
                raise ValueError("Archive member does not exist")
            factory = BytesIOFactory(limit=MAX_BYTES)
            archive.extract(targets=[member], factory=factory)
            stream = factory.get(member)
            stream.seek(0)
            content = stream.read(max_chars * 4 + 1)
    elif suffix == ".pdf":
        reader = PdfReader(path)
        pieces = []
        count = 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            pieces.append(f"[Page {number}]\n{text}")
            count += len(pieces[-1])
            if count > max_chars:
                break
        content = "\n".join(pieces).encode()
    else:
        with path.open("rb") as stream:
            content = stream.read(max_chars * 4 + 1)
        if b"\x00" in content:
            raise ValueError("Binary file is not a supported text document")
    text = content.decode("utf-8", errors="replace")
    return {"text": text[:max_chars], "truncated": len(text) > max_chars}


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def download_attachment(ctx: Context[Any, AppCtx], chat_id: int, message_id: str,
                                  file_id: int, filename: str, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
        """Download a FILE attachment. Use the exact message_id string from read_messages."""
        if not re.fullmatch(r"-?\d+", message_id):
            raise ValueError("message_id must be a decimal identifier string")
        positive_int("file_id", file_id, maximum=2**63 - 1)
        positive_int("max_bytes", max_bytes, maximum=MAX_BYTES)
        name = Path(filename).name
        if name != filename or name in ("", ".", "..") or "\\" in name or len(name.encode()) > 220:
            raise ValueError("filename must be a simple filename")
        client = ctx.request_context.lifespan_context.client
        info = await asyncio.wait_for(
            client.get_file_by_id(chat_id=chat_id, message_id=int(message_id), file_id=file_id),
            timeout=60,
        )
        if info is None or not info.url:
            raise ValueError("MAX did not return attachment download information")
        destination = root() / f"{file_id}-{name}"
        return await download(info.url, destination, max_bytes)

    @mcp.tool()
    async def read_attachment(path: str, max_chars: int = 20000, member: str | None = None) -> dict[str, Any]:
        """Read downloaded text/PDF, list ZIP/7z, or read a ZIP member without extracting it."""
        positive_int("max_chars", max_chars, maximum=200000)
        source = Path(path)
        if source.is_symlink():
            raise ValueError("Symlinks are not allowed")
        source = source.resolve(strict=True)
        if not source.is_relative_to(root()) or not source.is_file() or source.stat().st_size > MAX_BYTES:
            raise ValueError("Only bounded files in the download root can be read")
        return await asyncio.to_thread(inspect, source, max_chars, member)
