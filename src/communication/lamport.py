"""Per-node, thread-safe Lamport logical clock (UNG-100 / UNG-108).

Logical time is independent of the existing ISO-8601 wall-clock timestamp.
A local event or send increments by one; receipt uses max(local, remote) + 1.
"""
from __future__ import annotations

import threading


class LamportClock:
    def __init__(self, initial: int = 0):
        self._validate(initial)
        self._value = initial
        self._lock = threading.Lock()

    @staticmethod
    def _validate(timestamp: int) -> None:
        # bool is an int subclass, but is not a valid logical timestamp.
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("logical timestamp must be a nonnegative integer")

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def tick(self) -> int:
        """Increment BEFORE recording a local event."""
        with self._lock:
            self._value += 1
            return self._value

    def send(self) -> int:
        """Increment BEFORE each send; put the returned value on the wire."""
        return self.tick()

    def receive(self, timestamp: int) -> int:
        """BEFORE handling a received message: C = max(C, message.C) + 1."""
        self._validate(timestamp)
        with self._lock:
            self._value = max(self._value, timestamp) + 1
            return self._value
