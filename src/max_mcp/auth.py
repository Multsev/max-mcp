import argparse
import asyncio
import os
import pathlib
import stat
import sys

from pymax import (
    Client,
    ConsolePasswordProvider,
    ConsoleQrHandler,
    ConsoleSmsCodeProvider,
    WebClient,
)

SESSION_DIR = pathlib.Path.home() / ".max-mcp"
SESSION_FILE = "session.db"
KIND_FILE = "session.kind"
PHONE_FILE = "session.phone"


def _ensure_session_dir() -> None:
    SESSION_DIR.mkdir(mode=0o700, exist_ok=True)
    st = SESSION_DIR.lstat()
    if stat.S_ISLNK(st.st_mode):
        raise RuntimeError(f"{SESSION_DIR} is a symlink; refusing to use")
    if st.st_uid != os.getuid():
        raise RuntimeError(f"{SESSION_DIR} is not owned by current user")
    if st.st_mode & 0o077:
        SESSION_DIR.chmod(0o700)


def _write_secret(path: pathlib.Path, data: str) -> None:
    if path.is_symlink():
        path.unlink()
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _harden_session_file() -> None:
    path = SESSION_DIR / SESSION_FILE
    if path.is_symlink():
        raise RuntimeError(f"{path} is a symlink; refusing to chmod target")
    path.chmod(0o600)


def _mark_session(kind: str, phone: str | None = None) -> None:
    _write_secret(SESSION_DIR / KIND_FILE, kind)
    if phone:
        _write_secret(SESSION_DIR / PHONE_FILE, phone)


def _print_me(c) -> None:
    me = c.me
    print(
        f"Logged in as: {getattr(me, 'first_name', '?')} (id={getattr(me, 'id', '?')})",
        file=sys.stderr,
    )


async def _login_qr() -> None:
    _ensure_session_dir()
    client = WebClient(
        work_dir=str(SESSION_DIR),
        session_name=SESSION_FILE,
        qr_provider=ConsoleQrHandler(),
    )
    logged_in = asyncio.Event()

    @client.on_start()
    async def _ready(c: WebClient) -> None:
        _print_me(c)
        logged_in.set()
        await c.stop()

    try:
        await client.start()
    except asyncio.CancelledError:
        if not logged_in.is_set():
            raise
    _harden_session_file()
    _mark_session("web")


async def _login_sms(phone: str) -> None:
    _ensure_session_dir()
    client = Client(
        phone=phone,
        work_dir=str(SESSION_DIR),
        session_name=SESSION_FILE,
        sms_code_provider=ConsoleSmsCodeProvider(),
        password_provider=ConsolePasswordProvider(),
    )
    logged_in = asyncio.Event()

    @client.on_start()
    async def _ready(c: Client) -> None:
        _print_me(c)
        logged_in.set()
        await c.stop()

    try:
        await client.start()
    except asyncio.CancelledError:
        if not logged_in.is_set():
            raise
    _harden_session_file()
    _mark_session("sms", phone=phone)


def main() -> None:
    p = argparse.ArgumentParser(prog="max-mcp.auth")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login-qr", help="Scan QR with MAX mobile app")
    sms = sub.add_parser("login-sms", help="Phone + SMS code (works without phone app)")
    sms.add_argument("--phone", required=True, help="E.164 phone, e.g. +79991234567")
    sub.add_parser("login", help="Alias of login-qr (deprecated)")
    args = p.parse_args()

    if args.cmd in ("login-qr", "login"):
        asyncio.run(_login_qr())
    elif args.cmd == "login-sms":
        asyncio.run(_login_sms(args.phone))


if __name__ == "__main__":
    main()
