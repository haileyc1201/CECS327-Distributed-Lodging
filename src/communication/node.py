"""A coordination node: one TCP endpoint, one Lamport clock, several distributed algorithms.

``CoordinationNode`` is the host for the algorithms of this milestone:

* ``node.election`` - Bully leader election          (election.py)
* ``node.mutex``    - Ricart-Agrawala mutual exclusion (mutex.py)

Both components share the node's single logical clock (``node.clock``, the
clock of ``node.logger``) and its single listener, so every message the node
sends carries one consistent ``lc`` timestamp whichever algorithm sent it.

Wire convention (same as ring.py): one request per connection, answered by a
``<type>.reply`` envelope. A peer is ``{"name", "id", "host", "port"}``; ``id``
is the node's rank (higher id = stronger in the Bully election).
"""
from __future__ import annotations

import socket
from typing import Callable

from .codec import make_envelope
from .election import BullyElection
from .mutex import RicartAgrawala
from .server import FramedServer
from .transport import ConnectionClosed, connect, recv_message, send_message


class NodeError(OSError):
    """A remote node answered with an error."""


NET_ERRORS = (ConnectionClosed, socket.timeout, OSError, ValueError)


class CoordinationNode(FramedServer):
    def __init__(self, name: str, node_id: int, host: str = "127.0.0.1", port: int = 0):
        super().__init__(name, host, port)
        self.id = node_id
        self.me = {"name": name, "id": node_id, "host": self.host, "port": self.port}
        self.peers: list[dict] = []                       # every *other* node
        self._handlers: dict[str, Callable[[dict], dict]] = {}
        self.clock = self.logger.clock                    # this node's Lamport clock
        self.election = BullyElection(self)
        self.mutex = RicartAgrawala(self)

    # ------------------------------------------------------------ membership

    def set_peers(self, nodes: list[dict]) -> None:
        """Tell this node who is in the cluster (it may be in the list itself)."""
        self.peers = [n for n in nodes if n["name"] != self.name]

    # ------------------------------------------------------------ messaging

    def register(self, msg_type: str, fn: Callable[[dict], dict]) -> None:
        self._handlers[msg_type] = fn

    def call(self, peer: dict, msg_type: str, payload: dict, timeout: float = 3.0,
             read_timeout: float | None = None) -> dict:
        """Send one request to ``peer`` and return the reply payload.

        ``timeout`` bounds connect (and the reply unless ``read_timeout`` is given).
        Raises one of NET_ERRORS if the peer is unreachable or dies mid-call.
        """
        label = f"{peer['host']}:{peer['port']}"
        with connect(peer["host"], int(peer["port"]), timeout=timeout) as s:
            if read_timeout is not None:
                s.settimeout(read_timeout)
            send_message(s, make_envelope(msg_type, self.name, payload, receiver=peer["name"]),
                         self.logger, label)
            reply, _ = recv_message(s, self.logger, label)
        body = reply["payload"]
        if "error" in body:
            raise NodeError(body["error"])
        return body

    def try_call(self, peer: dict, msg_type: str, payload: dict, timeout: float = 3.0,
                 read_timeout: float | None = None) -> dict | None:
        """Like ``call`` but returns None (and logs) when the peer cannot be reached."""
        try:
            return self.call(peer, msg_type, payload, timeout, read_timeout)
        except NET_ERRORS as exc:
            self.logger.info(f"{msg_type} to {peer['name']} failed: {type(exc).__name__}: {exc}")
            return None

    def handle(self, conn, message, fmt, peer) -> bool:
        kind = message.get("type")
        fn = self._handlers.get(kind)
        if fn is None:
            return False
        try:
            payload = fn(message.get("payload") or {})
        except Exception as exc:  # noqa: BLE001 - report to the caller instead of killing the thread
            payload = {"error": f"{type(exc).__name__}: {exc}"}
        send_message(conn, make_envelope(kind + ".reply", self.name, payload, receiver=message.get("sender"),
                                         correlation_id=message.get("id")), self.logger, peer, fmt)
        return False  # one request per connection


def make_cluster(names_and_ids: list[tuple[str, int]], base_port: int = 0, **kw) -> list[CoordinationNode]:
    """Start nodes and tell each of them about all the others. ``base_port=0`` picks free ports."""
    nodes = [CoordinationNode(n, i, port=(base_port + k if base_port else 0), **kw).start()
             for k, (n, i) in enumerate(names_and_ids)]
    for n in nodes:
        n.set_peers([m.me for m in nodes])
    return nodes
