import asyncio
import zipfile
from pathlib import Path

import httpx
import pytest

from max_mcp.normalize import message_to_dict
from max_mcp.tools.attachments import download, inspect, validate_url


@pytest.mark.parametrize('url', ['http://max.ru/a','https://max.ru.evil.test/a','https://127.0.0.1/a','https://user@max.ru/a','https://max.ru:8443/a'])
def test_reject_untrusted_urls(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_large_message_id_preserved():
    value = 1234567890123456789
    assert message_to_dict({'id': value})['message_id'] == str(value)


def test_zip_member_read_without_extracting(tmp_path):
    archive = tmp_path / 'logs.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('../../outside.txt', 'diagnostic detail')
    assert inspect(archive, 10, '../../outside.txt') == {'text': 'diagnostic', 'truncated': True}
    assert not (tmp_path.parent / 'outside.txt').exists()


def test_download_limits_and_cleanup(tmp_path, monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'12345'))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    target = tmp_path / 'file.txt'
    with pytest.raises(ValueError):
        asyncio.run(download('https://max.ru/file', target, 4))
    assert list(tmp_path.iterdir()) == []
    result = asyncio.run(download('https://max.ru/file', target, 5))
    assert result['bytes'] == 5
    assert target.read_bytes() == b'12345'
    with pytest.raises(FileExistsError):
        asyncio.run(download('https://max.ru/file', target, 5))
    assert list(tmp_path.iterdir()) == [Path(target)]


def test_7z_member_read(tmp_path):
    import py7zr
    source = tmp_path / 'log.txt'
    source.write_text('test log')
    archive = tmp_path / 'log.7z'
    with py7zr.SevenZipFile(archive, 'w') as output:
        output.write(source, 'log.txt')
    assert inspect(archive, 100, 'log.txt')['text'] == 'test log'
