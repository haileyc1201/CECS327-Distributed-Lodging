"""Hop-by-hop LOOKUP routing through the ring overlay (UNG-92, parent UNG-79).

``LookupNode`` extends Josiah's ``RingNode`` (join / leave / crash repair) with one
new message, ``ring.lookup``. Unlike ``RingNode.get`` (which jumps straight to the
owner after ``find_successor``), a LOOKUP travels peer to peer:

    requester -> P1  ring.lookup {key, hops: 0, path: []}
    P1 is not responsible -> forwards to the closest next peer it knows
         (the farthest entry of its successor list that does not pass the key)
    P2 ... -> Pn  (each hop logged as "LOOKUP hop=N ...")
    Pn is responsible (key in (pred.id, Pn.id], see keymap.py) -> answers
    the reply {status: FOUND | NOT_FOUND, owner, hops, path, value}
         travels back along the same chain to the requester.

Every hop is written to logs/messages.jsonl as an info entry with the hop count,
next to the usual SEND/RECV entries of each ``ring.lookup`` message.
Any process (a peer, the Catalog, a client or a gateway) can start a lookup by
sending ``ring.lookup`` to any peer: see ``lookup_via``.
"""
from __future__ import annotations

from .codec import make_envelope
from .keymap import is_responsible, key_id
from .msglog import MessageLogger
from .ring import RING_SIZE, RingError, RingNode, between
from .transport import connect, recv_message, send_message

MAX_HOPS = 64  # safety net while the ring is being repaired


class LookupNode(RingNode):
    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 0):
        super().__init__(name, host, port)
        self._handlers["ring.lookup"] = self._h_lookup

    # ------------------------------------------------------------ routing

    def responsible_for(self, kid: int) -> bool:
        return is_responsible(kid, self.pred["id"], self.id)

    def next_hop(self, kid: int) -> dict:
        """Closest next peer toward ``kid``: the farthest known successor that does not pass it."""
        with self._lock:
            succs = list(self.succs)
        best = succs[0]
        for s in succs:
            if s["id"] != kid and between(s["id"], self.id, (kid - 1) % RING_SIZE):
                best = s
        return best

    def lookup(self, key: str) -> dict:
        """Start a LOOKUP here (hop 0) and return the reply that came back to me."""
        return self._h_lookup({"key": key, "origin": self.name, "hops": 0, "path": []})

    def _h_lookup(self, body: dict) -> dict:
        key = body["key"]
        kid = key_id(key)
        hops = int(body.get("hops", 0))
        path = list(body.get("path", [])) + [self.name]
        origin = body.get("origin", "?")
        if self.responsible_for(kid) or self._is_me(self.succ):
            with self._lock:
                found = key in self.data
                value = self.data.get(key)
            status = "FOUND" if found else "NOT_FOUND"
            self.logger.info(f"LOOKUP hop={hops} key={key} kid={kid} at {self.name}: responsible, {status}; "
                             f"reply to {origin} via {' -> '.join(reversed(path))}",
                             lookup={"key": key, "hop": hops, "at": self.name, "action": "answer", "status": status})
            return {"status": status, "key": key, "key_id": kid, "owner": self.name,
                    "owner_peer": self.me, "hops": hops, "path": path, "value": value}
        if hops >= MAX_HOPS:
            raise RingError(f"lookup for {key} exceeded {MAX_HOPS} hops")
        nxt = self.next_hop(kid)
        self.logger.info(f"LOOKUP hop={hops} key={key} kid={kid} at {self.name}: not responsible, "
                         f"forward to {nxt['name']} (id {nxt['id']})",
                         lookup={"key": key, "hop": hops, "at": self.name, "action": "forward", "next": nxt["name"]})
        return self._call(nxt, "ring.lookup", {"key": key, "origin": origin, "hops": hops + 1, "path": path})

    def put_routed(self, key: str, value) -> dict:
        """Route a LOOKUP to the key's responsible peer, then store the value there."""
        found = self.lookup(key)
        self._call(found["owner_peer"], "ring.store", {"key": key, "value": value})
        return found


def lookup_via(host: str, port: int, key: str, requester: str = "client", timeout: float = 5.0) -> dict:
    """Ask any peer at host:port to LOOKUP ``key``; returns the reply that comes back to the requester."""
    logger = MessageLogger(requester)
    label = f"{host}:{port}"
    with connect(host, port, timeout=timeout) as s:
        send_message(s, make_envelope("ring.lookup", requester,
                                      {"key": key, "origin": requester, "hops": 0, "path": []}),
                     logger, label)
        reply, _ = recv_message(s, logger, label)
    body = reply["payload"]
    if "error" in body:
        raise RingError(body["error"])
    return body
