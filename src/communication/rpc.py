"""JSON-RPC 2.0 over TCP sockets (request-reply).

The envelope payload of an ``rpc.request`` is a standard JSON-RPC 2.0 request::

    {"jsonrpc": "2.0", "method": "availability.check", "params": {"property_id": 101}, "id": 1}

and the ``rpc.reply`` payload is a JSON-RPC response with ``result`` or ``error``.
The reply envelope's ``correlation_id`` equals the request envelope's ``id``.
"""
from __future__ import annotations

import itertools
import socket
import threading
from typing import Any, Callable

from .codec import make_envelope
from .msglog import MessageLogger
from .server import FramedServer
from .transport import connect, recv_message, send_message


class RPCError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"[{code}] {message}")
        self.code, self.message, self.data = code, message, data


class RPCServer(FramedServer):
    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 0):
        super().__init__(name, host, port)
        self.methods: dict[str, Callable[..., Any]] = {"rpc.ping": lambda: "pong",
                                                        "rpc.methods": lambda: sorted(self.methods)}

    def register(self, method: str, fn: Callable[..., Any]) -> None:
        self.methods[method] = fn

    def handle(self, conn: socket.socket, message: dict, fmt: str, peer: str) -> bool:
        req = message.get("payload") or {}
        rid = req.get("id")
        fn = self.methods.get(req.get("method"))
        if message.get("type") != "rpc.request" or req.get("jsonrpc") != "2.0":
            body = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "Invalid Request"}}
        elif fn is None:
            body = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"Method not found: {req.get('method')}"}}
        else:
            try:
                params = req.get("params") or {}
                result = fn(**params) if isinstance(params, dict) else fn(*params)
                body = {"jsonrpc": "2.0", "id": rid, "result": result}
            except RPCError as e:
                body = {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message, "data": e.data}}
            except TypeError as e:
                body = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"Invalid params: {e}"}}
            except Exception as e:  # noqa: BLE001
                body = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(e)}}
        reply = make_envelope("rpc.reply", self.name, body, receiver=message.get("sender"),
                              correlation_id=message.get("id"))
        send_message(conn, reply, self.logger, peer, fmt)  # reply in the caller's format
        return True


class RPCClient:
    """Keeps one TCP connection open and performs blocking request-reply calls."""

    _ids = itertools.count(1)

    def __init__(self, sender: str, host: str, port: int, fmt: str = "json", timeout: float = 5.0):
        self.sender, self.host, self.port, self.fmt = sender, host, port, fmt
        self.logger = MessageLogger(sender)
        self.peer = f"{host}:{port}"
        self._sock = connect(host, port, timeout)
        self._lock = threading.Lock()

    def call(self, method: str, **params) -> Any:
        rid = next(self._ids)
        req = make_envelope("rpc.request", self.sender,
                            {"jsonrpc": "2.0", "method": method, "params": params, "id": rid})
        with self._lock:
            send_message(self._sock, req, self.logger, self.peer, self.fmt)
            reply, _ = recv_message(self._sock, self.logger, self.peer)
        assert reply["correlation_id"] == req["id"], "reply does not match request"
        body = reply["payload"]
        if "error" in body:
            err = body["error"]
            raise RPCError(err["code"], err["message"], err.get("data"))
        return body["result"]

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
