import json
import socket
import struct
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

PROTOCOL_VERSION = 1
MAX_MESSAGE_SIZE = 1_048_576  # 1 MiB safety limit
_HEADER = struct.Struct("!I")


class ProtocolError(Exception):
    """invalid message"""

class MsgType(str, Enum):
    # request-reply
    REQUEST = "request"
    REPLY = "reply"
    ERROR = "error"
    # publish-subscribe
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PUBLISH = "publish"
    EVENT = "event"          # broker -> subscriber delivery
    # group communication
    JOIN = "join"
    LEAVE = "leave"
    GROUP_MSG = "group_msg"
    # generic acknowledgement
    ACK = "ack"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Message:
    type: MsgType
    sender: str
    payload: dict = field(default_factory=dict)
    action: Optional[str] = None          # request-reply: what to do
    topic: Optional[str] = None           # pub-sub: topic name
    group: Optional[str] = None           # group communication: group name
    correlation_id: Optional[str] = None  # reply -> msg_id of the request
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: str = field(default_factory=_now)
    version: int = PROTOCOL_VERSION

    def describe(self) -> str:
        parts = [f"{self.type.value:<9}", f"id={self.msg_id}"]
        if self.correlation_id:
            parts.append(f"re={self.correlation_id}")
        for name in ("action", "topic", "group"):
            value = getattr(self, name)
            if value:
                parts.append(f"{name}={value}")
        return " ".join(parts)


def marshal(msg: Message) -> bytes: # marshal
    data = asdict(msg)
    data["type"] = msg.type.value
    try:
        return json.dumps(data, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"payload is not JSON-serialisable: {exc}") from exc


def unmarshal(body: bytes) -> Message: # unmarshalling
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ProtocolError("message must be a JSON object")

    missing = {"type", "sender", "msg_id", "timestamp"} - data.keys()
    if missing:
        raise ProtocolError(f"missing fields: {', '.join(sorted(missing))}")

    if data.get("version") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version: {data.get('version')}")

    try:
        msg_type = MsgType(data["type"])
    except ValueError:
        raise ProtocolError(f"unknown message type: {data['type']!r}") from None

    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be a JSON object")

    return Message(
        type=msg_type,
        sender=str(data["sender"]),
        payload=payload,
        action=data.get("action"),
        topic=data.get("topic"),
        group=data.get("group"),
        correlation_id=data.get("correlation_id"),
        msg_id=str(data["msg_id"]),
        timestamp=str(data["timestamp"]),
        version=data["version"],
    )


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]: # socket (read n bytes)
    chunks = []
    remaining = n
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            if remaining == n:
                return None  # clean close between messages
            raise ProtocolError("connection closed mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _peer(sock: socket.socket) -> str:
    try:
        host, port = sock.getpeername()[:2]
        return f"{host}:{port}"
    except OSError:
        return "?"


def send_message(sock: socket.socket, msg: Message, log=None) -> None:
    body = marshal(msg)
    sock.sendall(_HEADER.pack(len(body)) + body)
    if log:
        log.info(f"SENT   {msg.describe()} peer={_peer(sock)} bytes={len(body)}")


def recv_message(sock: socket.socket, log=None) -> Optional[Message]: # Read one framed messages
    header = _recv_exact(sock, _HEADER.size)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    if length > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"message too large: {length} bytes")
    body = _recv_exact(sock, length)
    if body is None:
        raise ProtocolError("connection closed mid-message")
    msg = unmarshal(body)
    if log:
        log.info(f"RECV   {msg.describe()} peer={_peer(sock)} bytes={length}")
    return msg


def make_request(sender: str, action: str, **payload) -> Message:
    return Message(MsgType.REQUEST, sender, payload=payload, action=action)


def make_reply(request: Message, sender: str, **payload) -> Message:
    return Message(MsgType.REPLY, sender, payload=payload,
                   action=request.action, correlation_id=request.msg_id)


def make_error(request: Optional[Message], sender: str, reason: str) -> Message:
    return Message(MsgType.ERROR, sender, payload={"message": reason},
                   action=request.action if request else None,
                   correlation_id=request.msg_id if request else None)


def call(host: str, port: int, request: Message, log=None, timeout: float = 5.0) -> Message: # Request reply
    with socket.create_connection((host, port), timeout=timeout) as sock:
        send_message(sock, request, log)
        reply = recv_message(sock, log)
    if reply is None:
        raise ProtocolError("connection closed before a reply arrived")
    if reply.correlation_id != request.msg_id:
        raise ProtocolError(
            f"reply {reply.msg_id} answers {reply.correlation_id}, expected {request.msg_id}"
        )
    return reply


def publish(host: str, port: int, topic: str, sender: str, log=None, **payload) -> bool: # Send to the broker
    msg = Message(MsgType.PUBLISH, sender, payload=payload, topic=topic)
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            send_message(sock, msg, log)
            recv_message(sock, log)  # ACK
        return True
    except (OSError, ProtocolError) as exc:
        if log:
            log.info(f"PUBLISH to broker failed: {exc}")
        return False