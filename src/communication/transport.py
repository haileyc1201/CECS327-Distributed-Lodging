"""Length-prefixed message framing over TCP sockets.

Frame layout::

    +-----------------+-------------+---------------------------+
    | 4 bytes length  | 1 byte fmt  | body (marshalled envelope) |
    +-----------------+-------------+---------------------------+

The length covers the body only. ``fmt`` is ``J`` (JSON) or ``X`` (XML).
Framing removes the 1024-byte ``recv`` limit of the Milestone 1 prototype and
lets several messages share one connection.
"""
from __future__ import annotations

import socket
import struct

from .codec import FORMAT_CODES, FORMATS, marshal, unmarshal
from .msglog import MessageLogger

HEADER = struct.Struct("!I")
MAX_FRAME = 16 * 1024 * 1024


class ConnectionClosed(Exception):
    pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionClosed("peer closed the connection")
        buf.extend(chunk)
    return bytes(buf)


def send_message(sock: socket.socket, message: dict, logger: MessageLogger, peer: str,
                 fmt: str = "json") -> None:
    body = marshal(message, fmt)
    logger.send(peer, message, body, fmt)
    sock.sendall(HEADER.pack(len(body)) + FORMATS[fmt] + body)


def recv_message(sock: socket.socket, logger: MessageLogger, peer: str) -> tuple[dict, str]:
    (length,) = HEADER.unpack(_recv_exact(sock, HEADER.size))
    if length > MAX_FRAME:
        raise ValueError(f"frame too large: {length}")
    fmt = FORMAT_CODES[_recv_exact(sock, 1)]
    body = _recv_exact(sock, length)
    message = unmarshal(body, fmt)
    logger.recv(peer, body, message, fmt)
    return message, fmt


def connect(host: str, port: int, timeout: float = 5.0) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=timeout)
    return sock


def listen(host: str, port: int) -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen()
    return srv
