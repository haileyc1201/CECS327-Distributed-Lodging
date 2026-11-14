"""Ricart-Agrawala distributed mutual exclusion (with Lamport timestamps).

No coordinator: a node that wants the critical section asks *every* other node
for permission, and enters only when all of them have replied.

    mutex.request {ts, node}   "I want the CS; my request has Lamport time ts"
    mutex.request.reply        the permission (sent at once, or later if deferred)

A node answers a request from *j* immediately unless

    * it is IN the critical section (HELD), or
    * it WANTS it too and its own request is older: (my_ts, my_name) < (ts_j, j)

in which case the reply is deferred until it leaves the critical section. The
(timestamp, name) pair is a total order, so exactly one of two competing nodes
yields and no two nodes are ever in the section together. A request waits in the
receiving node's handler thread, so the reply to ``mutex.request`` *is* the grant.

Fault handling (extension to the textbook version): a peer that cannot be
reached, or that dies while the request is pending, is treated as having
granted permission, otherwise one crash would block everybody forever.

Usage::

    with node.mutex.critical_section():
        ...touch the shared resource...
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from .transport import ConnectionClosed

if TYPE_CHECKING:
    from .node import CoordinationNode

RELEASED, WANTED, HELD = "RELEASED", "WANTED", "HELD"


class RicartAgrawala:
    def __init__(self, node: "CoordinationNode", grant_timeout: float = 30.0):
        self.node = node
        self.grant_timeout = grant_timeout      # longest a peer may keep us waiting for its reply
        self.state = RELEASED
        self.req_ts = 0                         # Lamport time of my current request
        self.entries = 0                        # how often this node has been in the CS
        self._cond = threading.Condition()
        node.register("mutex.request", self._h_request)

    # ------------------------------------------------------------ requesting side

    def acquire(self) -> None:
        n = self.node
        with self._cond:
            self.state = WANTED
            self.req_ts = n.clock.tick()        # the request's timestamp
            ts = self.req_ts
        n.logger.info(f"MUTEX {n.name} requests the critical section, ts={ts}",
                      mutex={"action": "request", "node": n.name, "ts": ts})
        threads = [threading.Thread(target=self._ask, args=(p, ts), daemon=True) for p in list(n.peers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()                            # all permissions in
        with self._cond:
            self.state = HELD
            self.entries += 1
        n.logger.info(f"MUTEX {n.name} ENTERS the critical section (request ts={ts})",
                      mutex={"action": "enter", "node": n.name, "ts": ts})

    def _ask(self, peer: dict, ts: int) -> None:
        n = self.node
        try:
            n.call(peer, "mutex.request", {"ts": ts, "node": n.name}, timeout=3.0, read_timeout=self.grant_timeout)
        except (ConnectionClosed, OSError, ValueError) as exc:   # unreachable, or died while we waited
            n.logger.info(f"MUTEX no reply from {peer['name']} ({type(exc).__name__}); treating it as granted",
                          mutex={"action": "peer-down", "peer": peer["name"]})

    def release(self) -> None:
        n = self.node
        n.logger.info(f"MUTEX {n.name} LEAVES the critical section",   # log first: once RELEASED the next
                      mutex={"action": "exit", "node": n.name})        # node may enter and log at once
        with self._cond:
            self.state = RELEASED
            self._cond.notify_all()             # wakes the handlers that deferred their replies

    @contextmanager
    def critical_section(self):
        self.acquire()
        try:
            yield
        finally:
            self.release()

    # ------------------------------------------------------------ replying side

    def _h_request(self, body: dict) -> dict:
        n = self.node
        theirs = (int(body["ts"]), body["node"])
        deferred = False
        with self._cond:
            while self.state == HELD or (self.state == WANTED and (self.req_ts, n.name) < theirs):
                if not deferred:
                    deferred = True
                    n.logger.info(f"MUTEX {n.name} defers the reply to {theirs[1]} (their ts={theirs[0]}; "
                                  f"I am {self.state}, my ts={self.req_ts})",
                                  mutex={"action": "defer", "node": n.name, "to": theirs[1]})
                self._cond.wait(timeout=0.5)
                if n._stop.is_set():
                    break
        return {"granted": True, "by": n.name}
