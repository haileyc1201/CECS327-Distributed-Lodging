"""ISO-8601 + Lamport timestamped message and event logging.

Every send, receive and local event is written as one JSON object per line
(JSON Lines) to

* ``logs/messages.jsonl`` - all nodes together (override with COMM_LOG_FILE), and
* ``nodes/<node>.jsonl`` beside that file - one log per node (override the
  directory with COMM_NODE_LOG_DIR); ``merge_logs.py`` turns these per-node
  logs into one total-ordered log,

and echoed to stdout in a readable form. Each SEND/RECV entry records the
message both *before* marshalling (the dict) and *after* (the wire text), which
documents the marshalling / unmarshalling step.

Each logger owns the node's Lamport clock (``logger.clock``). Every entry
carries its logical time as ``lc`` next to the wall-clock ``ts``:

    SEND   lc = the stamp on the message (the clock was ticked for the send)
    RECV   lc = max(local, message lc) + 1 (the clock after the receive)
    INFO / other local events   lc = the clock after ticking for the event

So within one node every entry has its own, strictly increasing ``lc``; the
pair ``(lc, node)`` identifies an event uniquely across the whole system.
A per-node re-entrant lock (``logger.event_lock``) makes "advance clock, write
entry" atomic, so concurrent handler threads cannot log the same ``lc`` twice.

Loggers are shared per node name within a process: every ``MessageLogger`` for
``node-A`` (the node's own, a short-lived ``RPCClient`` or ``lookup_via``
helper) uses the same clock and lock, so a new connection never restarts time.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import quote

from .clock import LamportClock
from .codec import now_iso

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "logs" / "messages.jsonl"
_lock = threading.Lock()
_registry_lock = threading.Lock()
# (pid, node name) -> (clock, event lock). The pid keeps a forked child from inheriting its parent's clock.
_states: dict[tuple[int, str], tuple[LamportClock, threading.RLock]] = {}
_handles: dict[str, object] = {}     # one open append-handle per log file, shared by every logger in this process


def _node_state(node: str) -> tuple[LamportClock, threading.RLock]:
    with _registry_lock:
        return _states.setdefault((os.getpid(), node), (LamportClock(), threading.RLock()))


def _handle_for(path: Path):
    """The open log file (call with ``_lock`` held). Opening it once matters: reopening it for every message
    is very slow on Windows (every open is scanned by antivirus) and, since all nodes share one lock, it made
    whole clusters crawl."""
    key = str(path)
    fh = _handles.get(key)
    if fh is None or fh.closed:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "a", encoding="utf-8", buffering=1)      # line buffered
        _handles[key] = fh
    return fh


def close_logs() -> None:
    """Close the log files (e.g. before deleting logs/messages.jsonl on Windows)."""
    with _lock:
        for fh in _handles.values():
            try:
                fh.close()
            except OSError:
                pass
        _handles.clear()


def log_path() -> Path:
    return Path(os.environ.get("COMM_LOG_FILE", DEFAULT_LOG))


def node_log_dir() -> Path:
    return Path(os.environ.get("COMM_NODE_LOG_DIR", log_path().parent / "nodes"))


class MessageLogger:
    def __init__(self, node: str, quiet: bool | None = None):
        if not isinstance(node, str) or not node:
            raise ValueError("node name must be a nonempty string")
        self.node = node
        self.quiet = bool(os.environ.get("COMM_QUIET")) if quiet is None else quiet
        self.clock, self.event_lock = _node_state(node)

    @property
    def node_path(self) -> Path:
        return node_log_dir() / (quote(self.node, safe="") + ".jsonl")

    def _write(self, entry: dict) -> None:
        path, node_path = log_path(), self.node_path
        line = json.dumps(entry, separators=(",", ":"))
        with _lock:
            for target in (path, node_path):
                fh = _handle_for(target)
                fh.write(line + "\n")
                fh.flush()                               # readers (tests, merge_logs) see it at once
        if not self.quiet:
            ev = entry["event"]
            msg = entry.get("message") or {}
            arrow = "->" if ev == "SEND" else "<-" if ev == "RECV" else "**"
            print(f"{entry['ts']} lc={entry.get('lc', ''):<4} [{self.node}] {ev:<5} {arrow} {entry.get('peer','')} "
                  f"type={msg.get('type', '')} id={msg.get('id', '')} "
                  f"fmt={entry.get('format', '')} bytes={entry.get('bytes', '')} "
                  f"{entry.get('note', '')}", flush=True)

    def send(self, peer: str, message: dict, wire: bytes, fmt: str) -> None:
        """Log a send; the caller (transport) has already ticked and stamped ``message['lc']``."""
        with self.event_lock:
            self._write({"ts": now_iso(), "lc": message.get("lc"), "node": self.node, "event": "SEND", "peer": peer,
                         "format": fmt, "bytes": len(wire),
                         "message": message,                      # before marshalling
                         "wire": wire.decode("utf-8", "replace")})  # after marshalling

    def recv(self, peer: str, wire: bytes, message: dict, fmt: str) -> None:
        """Apply the receive rule for ``message['lc']`` and log it, atomically. Invalid stamps raise ValueError."""
        with self.event_lock:
            lc = self.clock.update(message.get("lc"), strict=True)
            self._write({"ts": now_iso(), "lc": lc, "node": self.node, "event": "RECV", "peer": peer,
                         "format": fmt, "bytes": len(wire),
                         "wire": wire.decode("utf-8", "replace"),  # before unmarshalling
                         "message": message})                      # after unmarshalling

    def event(self, event: str, note: str = "", stamp: int | None = None, **extra) -> int:
        """Log a local event and return its ``lc``.

        Normally the clock is ticked for the event. Pass ``stamp`` when the caller has
        already ticked for it (e.g. the Lamport time of a mutex request) so the entry
        carries exactly that value instead of a second tick.
        """
        with self.event_lock:
            lc = self.clock.tick() if stamp is None else stamp
            entry = {"ts": now_iso(), "lc": lc, "node": self.node, "event": event}
            if note:
                entry["note"] = note
            self._write({**entry, **extra})
            return lc

    def info(self, note: str, stamp: int | None = None, **extra) -> int:
        return self.event("INFO", note, stamp=stamp, **extra)
