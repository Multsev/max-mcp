import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from max_mcp.normalize import (
    attach_to_dict,
    chat_to_dict,
    message_to_dict,
    post_to_dict,
)


class Preview(BaseModel):
    data: bytes


class Chat(BaseModel):
    id: int = 123
    title: str = "МТС — обсуждение"
    preview: Preview


class Message(BaseModel):
    id: int = 456
    chat_id: int = 123
    text: str = "Обновление готово ✅"
    attaches: list[Preview]
    stats: dict
    reaction_info: dict


def test_chat_ignores_binary_preview_without_decoding_it():
    chat = Chat(preview=Preview(data=b"\xee\x9d\xff"))
    # This is the original failure with an ordinary nested Pydantic model.
    with pytest.raises(UnicodeDecodeError):
        chat.model_dump(mode="json")
    result = chat_to_dict(chat)
    assert result["id"] == 123
    assert result["title"] == "МТС — обсуждение"
    assert "preview" not in result
    json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "payload", [b"", b"valid UTF-8", "Привет".encode(), bytes(range(256))]
)
@pytest.mark.parametrize("container", ["model", "dict", "namespace"])
def test_attachment_preserves_every_byte(payload, container):
    values = {"data": payload}
    att = {
        "model": lambda: Preview(**values),
        "dict": lambda: values,
        "namespace": lambda: SimpleNamespace(**values),
    }[container]()
    result = attach_to_dict(att)
    assert base64.urlsafe_b64decode(result["data"]) == payload
    assert isinstance(result["data"], str)
    json.dumps(result)


def test_message_and_post_nested_bytes_are_json_safe():
    raw = bytes(range(256))
    msg = Message(
        attaches=[Preview(data=raw)],
        stats={"nested": [raw]},
        reaction_info={"preview": raw},
    )
    for result in [message_to_dict(msg), post_to_dict(msg)]:
        assert result["text"] == msg.text
        assert base64.urlsafe_b64decode(result["attaches"][0]["data"]) == raw
        json.dumps(result, ensure_ascii=False)
    post = post_to_dict(msg)
    assert base64.urlsafe_b64decode(post["stats"]["nested"][0]) == raw
    assert base64.urlsafe_b64decode(post["reaction_info"]["preview"]) == raw


def test_dict_attachment_and_temporal_values_are_normalized():
    now = datetime(2026, 9, 15, tzinfo=UTC)
    result = message_to_dict(
        {"id": 1, "text": "Текст", "time": now, "attaches": [{"preview": b"\xff"}]}
    )
    assert result["time"] == "2026-09-15T00:00:00Z"
    assert result["attaches"][0]["preview"] == "_w=="
    json.dumps(result)
