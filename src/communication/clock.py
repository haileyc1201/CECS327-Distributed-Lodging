"""Lamport logical clock.

Every node owns one ``LamportClock`` (it lives on the node's ``MessageLogger``,
so the clock follows the node everywhere the logger is used). Rules:

    local event / send   t = t + 1                     (``tick``; the value is stamped on the message)
    receive              t = max(t, t_message) + 1     (``update``)

If event *a* happened-before event *b* then ``lc(a) < lc(b)``. The converse does
not hold, so two events with the same or ordered numbers may still be
concurrent; algorithms that need a total order (Ricart-Agrawala, merge_logs)
break ties with the node name: compare ``(lc, name)`` pairs.

All operations are thread-safe (one node serves many connections at once).
A stamp that is present but not a nonnegative integer (negative, bool, float,
string) is rejected with ``ValueError`` and the clock does not move: garbage on
the wire must never corrupt logical time. ``update(None)`` keeps its original
meaning (an unstamped event counts as a local event); the transport is stricter
and passes ``strict=True``, so a frame without ``lc`` is rejected.
"""
from __future__ import annotations

import threading


def validate_stamp(value) -> int:
    """Return ``value`` if it is a valid Lamport stamp (nonnegative int, not bool), else raise ValueError."""
    if type(value) is not int or value < 0:     # bool is an int subclass but not a timestamp
        raise ValueError(f"logical timestamp must be a nonnegative integer, got {value!r}")
    return value


class LamportClock:
    def __init__(self, start: int = 0):
        self._t = validate_stamp(start)
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

    def update(self, received: int | None, strict: bool = False) -> int:
        """Message receive: jump past the sender's timestamp.

        A missing stamp (None) counts as a local event, unless ``strict`` (then it is rejected).
        Invalid stamps raise ValueError without advancing the clock.
        """
        if received is None and not strict:
            return self.tick()
        validate_stamp(received)
        with self._lock:
            self._t = max(self._t, received) + 1
            return self._t

    def __repr__(self) -> str:
        return f"LamportClock({self.time})"
