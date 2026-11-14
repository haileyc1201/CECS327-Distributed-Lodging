"""Lamport logical clock.

Every node owns one ``LamportClock`` (it lives on the node's ``MessageLogger``,
so the clock follows the node everywhere the logger is used). Rules:

    local event / send   t = t + 1                     (``tick``; the value is stamped on the message)
    receive              t = max(t, t_message) + 1     (``update``)

If event *a* happened-before event *b* then ``lc(a) < lc(b)``. The converse does
not hold, so two events with the same or ordered numbers may still be
concurrent; algorithms that need a total order (Ricart-Agrawala) break ties
with the node name: compare ``(lc, name)`` pairs.
"""
from __future__ import annotations

import threading


class LamportClock:
    def __init__(self, start: int = 0):
        self._t = start
        self._lock = threading.Lock()

    @property
    def time(self) -> int:
        with self._lock:
            return self._t

    def tick(self) -> int:
        """Local event or message send: advance by one and return the new time."""
        with self._lock:
            self._t += 1
            return self._t

    def update(self, received: int | None) -> int:
        """Message receive: jump past the sender's timestamp. A missing stamp counts as a local event."""
        with self._lock:
            self._t = max(self._t, int(received or 0)) + 1
            return self._t

    def __repr__(self) -> str:
        return f"LamportClock({self.time})"
