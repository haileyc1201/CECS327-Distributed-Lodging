"""Publish-subscribe broker over TCP sockets.

Protocol (all messages are envelopes):

    subscriber -> broker  subscribe   {"topics": ["booking.created"]}
    broker -> subscriber  subscribe.ack {"topics": [...], "subscriber": "notification-service"}
    publisher  -> broker  publish     {"topic": "booking.created", "event": {...}}
    broker -> publisher   publish.ack {"topic": ..., "delivered_to": ["audit-service", ...]}
    broker -> subscriber  event       {"topic": ..., "event": {...}, "seq": 7}

The broker decouples publishers from subscribers: the Reservation node does not
know who is listening. Every subscriber of a topic gets its own copy of the event.
"""
from __future__ import annotations

import itertools
import socket
import threading
from typing import Callable

from .codec import make_envelope
from .msglog import MessageLogger
from .server import FramedServer
from .transport import ConnectionClosed, connect, recv_message, send_message


class Broker(FramedServer):
    def __init__(self, name: str = "broker", host: str = "127.0.0.1", port: int = 0):
        super().__init__(name, host, port)
        self._subs: dict[str, list[tuple[str, socket.socket, str, str]]] = {}
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._send_locks: dict[int, threading.Lock] = {}

    def subscribers(self, topic: str) -> list[str]:
        with self._lock:
            return [s[0] for s in self._subs.get(topic, [])]

    def handle(self, conn, message, fmt, peer) -> bool:
        kind, body = message.get("type"), message.get("payload") or {}
        if kind == "subscribe":
            topics = body.get("topics") or []
            with self._lock:
                self._send_locks.setdefault(id(conn), threading.Lock())
                for t in topics:
                    self._subs.setdefault(t, []).append((message["sender"], conn, fmt, peer))
            ack = make_envelope("subscribe.ack", self.name, {"topics": topics, "subscriber": message["sender"]},
                                receiver=message["sender"], correlation_id=message["id"])
            with self._send_locks[id(conn)]:
                send_message(conn, ack, self.logger, peer, fmt)
            return True
        if kind == "publish":
            topic = body["topic"]
            seq = next(self._seq)
            with self._lock:
                targets = list(self._subs.get(topic, []))
            delivered, failed = [], []
            for name, sconn, sfmt, speer in targets:
                ev = make_envelope("event", self.name, {"topic": topic, "seq": seq, "event": body.get("event"),
                                                        "publisher": message["sender"]}, receiver=name)
                try:
                    with self._send_locks.setdefault(id(sconn), threading.Lock()):
                        send_message(sconn, ev, self.logger, speer, sfmt)
                    delivered.append(name)
                except OSError:
                    failed.append(name)
                    self.on_disconnect(sconn)
            ack = make_envelope("publish.ack", self.name, {"topic": topic, "seq": seq, "delivered_to": delivered,
                                                           "failed": failed},
                                receiver=message["sender"], correlation_id=message["id"])
            send_message(conn, ack, self.logger, peer, fmt)
            return True
        if kind == "topics":
            with self._lock:
                view = {t: [s[0] for s in subs] for t, subs in self._subs.items()}
            send_message(conn, make_envelope("topics.reply", self.name, view, correlation_id=message["id"]),
                         self.logger, peer, fmt)
            return True
        return False

    def on_disconnect(self, conn) -> None:
        with self._lock:
            for t in list(self._subs):
                self._subs[t] = [s for s in self._subs[t] if s[1] is not conn]


class Publisher:
    def __init__(self, sender: str, host: str, port: int, fmt: str = "json"):
        self.sender, self.fmt, self.peer = sender, fmt, f"{host}:{port}"
        self.logger = MessageLogger(sender)
        self._sock = connect(host, port)
        self._lock = threading.Lock()

    def publish(self, topic: str, event: dict) -> dict:
        msg = make_envelope("publish", self.sender, {"topic": topic, "event": event}, receiver="broker")
        with self._lock:
            send_message(self._sock, msg, self.logger, self.peer, self.fmt)
            ack, _ = recv_message(self._sock, self.logger, self.peer)
        return ack["payload"]

    def close(self):
        self._sock.close()


class Subscriber:
    """Connects to the broker, subscribes, then receives pushed events on a background thread."""

    def __init__(self, name: str, host: str, port: int, topics: list[str],
                 handler: Callable[[dict], None] | None = None, fmt: str = "json"):
        self.name, self.topics, self.fmt, self.peer = name, topics, fmt, f"{host}:{port}"
        self.logger = MessageLogger(name)
        self.received: list[dict] = []
        self.handler = handler
        self._sock = connect(host, port, timeout=None)
        self.ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "Subscriber":
        sub = make_envelope("subscribe", self.name, {"topics": self.topics}, receiver="broker")
        send_message(self._sock, sub, self.logger, self.peer, self.fmt)
        self._thread.start()
        self.ready.wait(5)
        return self

    def _run(self):
        try:
            while True:
                msg, _ = recv_message(self._sock, self.logger, self.peer)
                if msg["type"] == "subscribe.ack":
                    self.ready.set()
                elif msg["type"] == "event":
                    self.received.append(msg["payload"])
                    if self.handler:
                        self.handler(msg["payload"])
        except (ConnectionClosed, OSError):
            pass

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass
