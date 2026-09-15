from enum import Enum
from typing import Any

from pydantic_core import to_jsonable_python


def _dump(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        # PyMax models contain binary previews, including in unused chat fields.
        # Keep bytes intact until we have selected the public response fields.
        dumped = dump(mode="python", exclude_none=True)
        return dumped if isinstance(dumped, dict) else {}
    try:
        return vars(obj)
    except TypeError:
        return {}


def _value(d: dict[str, Any], key: str, obj: Any, attr: str | None = None) -> Any:
    value = d.get(key)
    if value is not None:
        return value
    return getattr(obj, attr or key, None)


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    text = str(value)
    return text.rsplit(".", 1)[-1]


def _entity_id(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("id")
    return getattr(value, "id", value)


def chat_to_dict(chat: Any) -> dict[str, Any]:
    d = _dump(chat)
    owner = d.get("owner_id")
    if owner is None:
        owner = _value(d, "owner", chat)
    return to_jsonable_python(
        {
            "id": _value(d, "id", chat),
            "title": _value(d, "title", chat),
            "type": _enum_text(_value(d, "type", chat)),
            "last_event_time": _value(d, "last_event_time", chat),
            "participants_count": _value(d, "participants_count", chat),
            "description": _value(d, "description", chat),
            "owner_id": _entity_id(owner),
        },
        bytes_mode="base64",
    )


def attach_to_dict(att: Any) -> dict[str, Any]:
    d = _dump(att)
    if not isinstance(d, dict):
        return {"value": d, "_kind": type(att).__name__}
    out = dict(d)
    out.setdefault("_kind", type(att).__name__)
    return to_jsonable_python(out, bytes_mode="base64")


def _reply_to_id(msg: Any, d: dict[str, Any]) -> int | None:
    msg_type = _enum_text(_value(d, "type", msg))
    if msg_type == "REPLY":
        return _value(d, "prev_message_id", msg)
    return None


def message_to_dict(msg: Any) -> dict[str, Any]:
    d = _dump(msg)
    out = {
        "id": _value(d, "id", msg),
        "chat_id": _value(d, "chat_id", msg),
        "sender": _entity_id(_value(d, "sender", msg)),
        "text": _value(d, "text", msg),
        "time": _value(d, "time", msg),
        "type": _enum_text(_value(d, "type", msg)),
        "reply_to_id": _reply_to_id(msg, d),
    }
    attaches = _value(d, "attaches", msg) or []
    if attaches:
        out["attaches"] = [
            attach_to_dict(attachment)
            if not isinstance(attachment, dict)
            else dict(attachment)
            for attachment in attaches
        ]
    return to_jsonable_python(out, bytes_mode="base64")


def post_to_dict(msg: Any) -> dict[str, Any]:
    base = message_to_dict(msg)
    d = _dump(msg)
    reaction_info = _value(d, "reaction_info", msg)
    stats = _value(d, "stats", msg)
    if reaction_info is not None:
        base["reaction_info"] = reaction_info
    if stats is not None:
        base["stats"] = stats
    return to_jsonable_python(base, bytes_mode="base64")
