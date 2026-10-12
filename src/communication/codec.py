"""Marshalling and unmarshalling of message envelopes.

Every message on the wire is an *envelope* (a Python dict) with this shape::

    {
      "id": "3f2a9c1e7b4d",            # unique message id
      "type": "rpc.request",            # message kind
      "sender": "client",               # logical node name
      "receiver": "reservation-rpc",    # optional
      "timestamp": "2026-10-12T23:01:02.123Z",  # ISO-8601 UTC
      "correlation_id": null,           # id of the request this replies to
      "payload": {...}                  # message-specific body
    }

Two structured formats are supported:
    * JSON (default, format code ``J``)
    * XML  (format code ``X``) - a typed, lossless mapping of the same dict
"""
from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

FORMATS = {"json": b"J", "xml": b"X"}
FORMAT_CODES = {v: k for k, v in FORMATS.items()}


def now_iso() -> str:
    """Current UTC time as ISO-8601 with millisecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_envelope(msg_type: str, sender: str, payload: Any, receiver: str | None = None,
                  correlation_id: str | None = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "type": msg_type,
        "sender": sender,
        "receiver": receiver,
        "timestamp": now_iso(),
        "correlation_id": correlation_id,
        "payload": payload,
    }


# ---------------------------------------------------------------- JSON

def marshal_json(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=False).encode("utf-8")


def unmarshal_json(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------- XML

def _to_xml(parent: ET.Element, tag: str, value: Any) -> None:
    el = ET.SubElement(parent, tag)
    if value is None:
        el.set("t", "null")
    elif isinstance(value, bool):
        el.set("t", "bool")
        el.text = "true" if value else "false"
    elif isinstance(value, int):
        el.set("t", "int")
        el.text = str(value)
    elif isinstance(value, float):
        el.set("t", "float")
        el.text = repr(value)
    elif isinstance(value, str):
        el.set("t", "str")
        el.text = value
    elif isinstance(value, dict):
        el.set("t", "dict")
        for k, v in value.items():
            child_parent = ET.SubElement(el, "entry")
            child_parent.set("key", str(k))
            _to_xml(child_parent, "value", v)
    elif isinstance(value, (list, tuple)):
        el.set("t", "list")
        for v in value:
            _to_xml(el, "item", v)
    else:
        raise TypeError(f"cannot marshal {type(value).__name__} to XML")


def _from_xml(el: ET.Element) -> Any:
    t = el.get("t")
    text = el.text or ""
    if t == "null":
        return None
    if t == "bool":
        return text == "true"
    if t == "int":
        return int(text)
    if t == "float":
        return float(text)
    if t == "str":
        return text
    if t == "dict":
        return {entry.get("key"): _from_xml(entry.find("value")) for entry in el.findall("entry")}
    if t == "list":
        return [_from_xml(item) for item in el.findall("item")]
    raise ValueError(f"unknown XML type attribute {t!r}")


def marshal_xml(obj: dict) -> bytes:
    root = ET.Element("message")
    _to_xml(root, "envelope", obj)
    return ET.tostring(root, encoding="utf-8")


def unmarshal_xml(data: bytes) -> dict:
    root = ET.fromstring(data.decode("utf-8"))
    return _from_xml(root.find("envelope"))


# ---------------------------------------------------------------- public API

def marshal(obj: dict, fmt: str = "json") -> bytes:
    """Convert an in-memory envelope (dict) into bytes for the wire."""
    if fmt == "json":
        return marshal_json(obj)
    if fmt == "xml":
        return marshal_xml(obj)
    raise ValueError(f"unsupported format {fmt}")


def unmarshal(data: bytes, fmt: str = "json") -> dict:
    """Convert wire bytes back into an in-memory envelope (dict)."""
    if fmt == "json":
        return unmarshal_json(data)
    if fmt == "xml":
        return unmarshal_xml(data)
    raise ValueError(f"unsupported format {fmt}")
