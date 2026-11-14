"""A shared resource that must never be used by two nodes at the same time.

``SharedResource`` is a counter kept by one server. ``resource.update`` is a
deliberately *non-atomic* read-modify-write (it reads, "works" for a moment,
then writes), exactly the kind of operation that loses updates when two nodes
run it concurrently. The resource does not protect itself: the protection comes
from the distributed mutual exclusion (Ricart-Agrawala). What the resource does
is *detect* misuse: every call that starts while another one is still running
is recorded in ``violations``.

    with RPCClient(...) as c: c.call("resource.update", node="A")      # unprotected
    update_resource(node, addr)                                         # protected by node.mutex

A correct run therefore ends with ``value == number of updates`` and
``violations == []``; an unprotected run shows lost updates and violations.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from .rpc import RPCClient, RPCServer

if TYPE_CHECKING:
    from .node import CoordinationNode


class SharedResource(RPCServer):
    def __init__(self, name: str = "shared-resource", host: str = "127.0.0.1", port: int = 0,
                 work_time: float = 0.02):
        super().__init__(name, host, port)
        self.work_time = work_time              # how long one update takes (widens the race window)
        self.value = 0
        self.history: list[dict] = []           # one entry per completed update, in order
        self.violations: list[dict] = []        # overlapping accesses that were detected
        self._active: list[str] = []
        self._meta = threading.Lock()           # protects only the bookkeeping, NOT the update itself
        self.register("resource.update", self.update)
        self.register("resource.state", self.state)

    def update(self, node: str, delta: int = 1) -> dict:
        with self._meta:
            if self._active:
                self.violations.append({"node": node, "overlaps_with": list(self._active)})
                self.logger.info(f"VIOLATION: {node} entered while {self._active} was inside")
            self._active.append(node)
        try:
            before = self.value                 # read
            time.sleep(self.work_time)          # work inside the critical section
            self.value = before + delta         # write
            self.history.append({"node": node, "before": before, "after": self.value, "lc": self.logger.clock.time})
            self.logger.info(f"{node} updated the resource {before} -> {self.value}")
            return {"before": before, "after": self.value}
        finally:
            with self._meta:
                self._active.remove(node)

    def state(self) -> dict:
        with self._meta:
            return {"value": self.value, "updates": len(self.history), "violations": list(self.violations)}


def update_resource(node: "CoordinationNode", addr: tuple[str, int], delta: int = 1, protected: bool = True) -> dict:
    """One update of the shared resource on behalf of ``node`` (uses the node's clock)."""
    def call() -> dict:
        with RPCClient(node.name, addr[0], addr[1], logger=node.logger) as c:
            return c.call("resource.update", node=node.name, delta=delta)

    if protected:
        with node.mutex.critical_section():
            return call()
    return call()
