"""Ring overlay (Chord-style) with peer join, graceful leave and crash repair.

Every peer hashes its name to a position (``id``) on a ring of 2**16 slots and
knows only its neighbours: a predecessor and a short successor list. A key is
owned by the first peer at or after the key's hash (its *successor*), so a peer
owns the keys in (predecessor.id, own id]. Each peer also keeps a replica of
its predecessor's keys, so one crash loses no data.

    Join   joiner -> bootstrap  ring.find_successor {id}        (walks the ring)
           joiner -> successor  ring.join_at {peer}             -> {predecessor, data}
           successor -> old pred ring.set_successor {peer}      (neighbours updated)
    Leave  leaver -> successor  ring.take_data {data}           (hand over keys)
           leaver -> successor  ring.set_predecessor {peer}
           leaver -> pred       ring.set_successor {peer, drop}
    Crash  every peer pings its successor (ring.ping, via stabilize()); on timeout it
           drops the dead peer, links to the next live one with ring.set_predecessor
           {promote: true} (which promotes the replica to primary data) and re-replicates.
    Data   ring.store / ring.fetch go to the key's owner; ring.replicate copies the
           owner's keys to its successor. ring.state describes a peer.

A "peer" on the wire is {"name", "host", "port", "id"}. Each request is one
short-lived connection answered by one ``<type>.reply`` envelope.
"""
from __future__ import annotations

import hashlib
import socket
import threading

from .codec import make_envelope
from .server import FramedServer
from .transport import ConnectionClosed, connect, recv_message, send_message

ID_BITS = 16
RING_SIZE = 1 << ID_BITS
SUCC_LIST = 3  # how many successors to remember, so one crash never leaves a peer without a next hop


class RingError(OSError):
    """A remote peer answered with an error."""


NET_ERRORS = (ConnectionClosed, socket.timeout, OSError, ValueError)


def ring_id(name: str) -> int:
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16) % RING_SIZE


def between(x: int, a: int, b: int) -> bool:
    """True if x lies in the ring interval (a, b]. a == b means the whole ring."""
    if a < b:
        return a < x <= b
    return x > a or x <= b


class RingNode(FramedServer):
    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 0):
        super().__init__(name, host, port)
        self.id = ring_id(name)
        self.me = {"name": name, "host": self.host, "port": self.port, "id": self.id}
        self.pred: dict = self.me          # alone: my own neighbour on both sides
        self.succs: list[dict] = [self.me]
        self.data: dict[str, object] = {}      # keys I own
        self.replicas: dict[str, object] = {}  # copy of my predecessor's keys
        self._lock = threading.RLock()
        self._handlers = {
            "ring.find_successor": self._h_find_successor,
            "ring.join_at": self._h_join_at,
            "ring.set_successor": self._h_set_successor,
            "ring.set_predecessor": self._h_set_predecessor,
            "ring.take_data": self._h_take_data,
            "ring.replicate": self._h_replicate,
            "ring.ping": self._h_ping,
            "ring.store": self._h_store,
            "ring.fetch": self._h_fetch,
            "ring.state": lambda body: self.state(),
        }

    # ------------------------------------------------------------ helpers

    @property
    def succ(self) -> dict:
        return self.succs[0]

    def _is_me(self, peer: dict) -> bool:
        return peer["name"] == self.name

    def _set_succs(self, peers: list[dict]) -> None:
        seen: set[str] = set()
        out = []
        for p in peers:
            if self._is_me(p) or p["name"] in seen:
                continue
            seen.add(p["name"])
            out.append(p)
        self.succs = out[:SUCC_LIST] or [self.me]

    def _call(self, peer: dict, msg_type: str, payload: dict) -> dict:
        if self._is_me(peer):
            return self._handlers[msg_type](payload)
        addr = (peer["host"], int(peer["port"]))
        label = f"{addr[0]}:{addr[1]}"
        with connect(*addr, timeout=3) as s:
            send_message(s, make_envelope(msg_type, self.name, payload, receiver=peer["name"]), self.logger, label)
            reply, _ = recv_message(s, self.logger, label)
        body = reply["payload"]
        if "error" in body:
            raise RingError(body["error"])
        return body

    def _try(self, peer: dict, msg_type: str, payload: dict) -> dict | None:
        try:
            return self._call(peer, msg_type, payload)
        except NET_ERRORS as exc:
            self.logger.info(f"{msg_type} to {peer['name']} failed: {type(exc).__name__}: {exc}")
            return None

    def _find(self, kid: int) -> dict:
        s = self.succ
        if self._is_me(s) or between(kid, self.id, s["id"]):
            return s
        return self._call(s, "ring.find_successor", {"id": kid})["peer"]

    def _replicate(self) -> None:
        """Push a copy of my keys to my successor."""
        s = self.succ
        if self._is_me(s):
            return
        with self._lock:
            snapshot = dict(self.data)
        self._try(s, "ring.replicate", {"data": snapshot})

    def state(self) -> dict:
        with self._lock:
            return {"name": self.name, "id": self.id, "pred": self.pred["name"],
                    "succs": [s["name"] for s in self.succs],
                    "keys": sorted(self.data), "replicas": sorted(self.replicas)}

    # ------------------------------------------------------------ public API

    def join(self, host: str, port: int) -> None:
        """Join the ring through a bootstrap peer at host:port."""
        bootstrap = {"name": "bootstrap", "host": host, "port": port, "id": -1}
        succ = self._call(bootstrap, "ring.find_successor", {"id": self.id})["peer"]       # find position
        if succ["id"] == self.id:
            raise ValueError(f"ring position {self.id} is already taken by {succ['name']}")
        reply = self._call(succ, "ring.join_at", {"peer": self.me})                          # update neighbours
        with self._lock:
            self._set_succs([succ])
            self.pred = reply["predecessor"]
            self.data.update(reply["data"])                                                  # keys I now own
        self._replicate()
        self.logger.info(f"joined ring at {self.id} between {self.pred['name']} and {succ['name']}")

    def leave(self) -> None:
        """Graceful leave: hand my keys to the successor and link my neighbours together."""
        s, p = self.succ, self.pred
        if not self._is_me(s):
            with self._lock:
                data = dict(self.data)
            self._try(s, "ring.take_data", {"data": data})
            self._try(s, "ring.set_predecessor", {"peer": p, "promote": False})
            if not self._is_me(p):
                self._try(p, "ring.set_successor", {"peer": s, "drop": self.name})
        with self._lock:
            self.pred, self.succs = self.me, [self.me]
            self.data, self.replicas = {}, {}
        self.logger.info("left ring")

    def stabilize(self) -> list[str]:
        """One heartbeat round: ping the successor; repair around it if it is dead.

        Every peer is somebody's successor, so this alone detects every crash.
        Returns the names of crashed peers repaired during this round.
        """
        crashed: list[str] = []
        while not self._is_me(self.succ):
            s = self.succ
            try:
                reply = self._call(s, "ring.ping", {})
            except NET_ERRORS:
                crashed.append(s["name"])
                with self._lock:
                    self._set_succs(self.succs[1:])
                    new = self.succ
                    if self._is_me(new):                       # nobody left but me
                        self.pred = self.me
                        self.data.update(self.replicas)
                        self.replicas = {}
                if not self._is_me(new):
                    self._try(new, "ring.set_predecessor", {"peer": self.me, "promote": True})
                    self._replicate()
                self.logger.info(f"successor {s['name']} timed out; repaired, next is {new['name']}")
                continue
            with self._lock:
                self._set_succs([s] + reply["succs"])          # refresh the successor list
                tail = self.succs[1:]
            live = [p for p in tail if self._try(p, "ring.ping", {}) is not None]  # drop dead tail entries
            with self._lock:
                self._set_succs([s] + live)
            break
        return crashed

    def put(self, key: str, value) -> str:
        owner = self._find(ring_id(key))
        return self._call(owner, "ring.store", {"key": key, "value": value})["owner"]

    def get(self, key: str) -> dict:
        owner = self._find(ring_id(key))
        return self._call(owner, "ring.fetch", {"key": key})

    # ------------------------------------------------------------ request handlers

    def _h_find_successor(self, body: dict) -> dict:
        return {"peer": self._find(int(body["id"]))}

    def _h_join_at(self, body: dict) -> dict:
        """I am the joiner's successor: give it its keys and slot it in before me."""
        joiner = body["peer"]
        with self._lock:
            old_pred = self.pred
            moved = {k: v for k, v in self.data.items() if between(ring_id(k), old_pred["id"], joiner["id"])}
            for k in moved:
                del self.data[k]
            self.replicas = dict(moved)          # my predecessor is now the joiner, whose keys these are
            self.pred = joiner
            if self._is_me(old_pred):            # I was alone: the joiner is my successor too
                self._set_succs([joiner])
        if self._is_me(old_pred):
            self._replicate()
        else:
            self._try(old_pred, "ring.set_successor", {"peer": joiner})
        return {"predecessor": old_pred, "data": moved}

    def _h_set_successor(self, body: dict) -> dict:
        drop = body.get("drop")
        with self._lock:
            self._set_succs([body["peer"]] + [s for s in self.succs if s["name"] != drop])
        self._replicate()
        return {}

    def _h_set_predecessor(self, body: dict) -> dict:
        with self._lock:
            self.pred = body["peer"]
            if body.get("promote"):              # predecessor crashed: its replica becomes my data
                self.data.update(self.replicas)
                self.replicas = {}
        if body.get("promote"):
            self._replicate()
        return {}

    def _h_take_data(self, body: dict) -> dict:
        with self._lock:
            self.data.update(body["data"])
        self._replicate()
        return {}

    def _h_replicate(self, body: dict) -> dict:
        with self._lock:
            self.replicas = dict(body["data"])
        return {}

    def _h_ping(self, body: dict) -> dict:
        with self._lock:
            return {"name": self.name, "succs": list(self.succs)}

    def _h_store(self, body: dict) -> dict:
        with self._lock:
            self.data[body["key"]] = body["value"]
        self._replicate()
        return {"owner": self.name}

    def _h_fetch(self, body: dict) -> dict:
        with self._lock:
            found = body["key"] in self.data
            return {"owner": self.name, "found": found, "value": self.data.get(body["key"])}

    # ------------------------------------------------------------ wire

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
