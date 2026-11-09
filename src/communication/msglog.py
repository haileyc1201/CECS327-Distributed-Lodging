"""Logical and ISO-8601 timestamped message logging.

Every send and receive is written as one JSON object per line (JSON Lines) to
``logs/messages.jsonl`` (override with the COMM_LOG_FILE environment variable)
and to ``nodes/<node-id>.jsonl`` beside that file (override directory with
``COMM_NODE_LOG_DIR``), and echoed to stdout in a readable form. Each entry records the message both
*before* marshalling (the dict) and *after* (the wire text), which documents
the marshalling / unmarshalling step.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import quote

from .lamport import LamportClock

from .codec import now_iso

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "logs" / "messages.jsonl"
_lock = threading.Lock()
_registry_lock = threading.Lock()
# Helper clients are often short-lived (coordinator_request / lookup_via).
# Sharing by logical name, not by connection/logger, prevents clock resets.
# PID in the key also prevents a forked child inheriting its parent's clock.
_states: dict[tuple[int, str], tuple[LamportClock, object]] = {}


def _node_state(node: str):
    with _registry_lock:
        return _states.setdefault((os.getpid(), node), (LamportClock(), threading.RLock()))


def log_path() -> Path:
    return Path(os.environ.get("COMM_LOG_FILE", DEFAULT_LOG))


class MessageLogger:
    def __init__(self, node: str, quiet: bool | None = None):
        if not isinstance(node, str) or not node:
            raise ValueError("node id must be a nonempty string")
        self.node = node
        self.clock, self.event_lock = _node_state(node)
        self.quiet = bool(os.environ.get("COMM_QUIET")) if quiet is None else quiet

    @property
    def node_path(self) -> Path:
        directory = Path(os.environ.get("COMM_NODE_LOG_DIR", log_path().parent / "nodes"))
        return directory / (quote(self.node, safe="") + ".jsonl")

    def _write(self, entry: dict) -> None:
        path = log_path()
        node_path = self.node_path
        path.parent.mkdir(parents=True, exist_ok=True)
        node_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, separators=(",", ":"))
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            with open(node_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if not self.quiet:
            ev = entry["event"]
            msg = entry.get("message") or {}
            arrow = "->" if ev == "SEND" else "<-" if ev == "RECV" else "**"
            print(f"{entry['ts']} L={entry['timestamp']} [{self.node}] {ev:<5} {arrow} {entry.get('peer','')} "
                  f"type={msg.get('type', '')} id={msg.get('id', '')} "
                  f"fmt={entry.get('format', '')} bytes={entry.get('bytes', '')} "
                  f"{entry.get('note', '')}", flush=True)

    def _entry(self, timestamp: int, event: str, details: dict, **legacy) -> None:
        # Canonical M4 schema; retain M2 fields for existing demos and reports.
        self._write({**legacy, "ts": now_iso(), "timestamp": timestamp,
                     "node_id": self.node, "node": self.node,
                     "event": event, "details": details})

    def send(self, peer: str, message: dict, wire: bytes, fmt: str) -> None:
        # transport holds event_lock and has already ticked before marshalling.
        with self.event_lock:
            self._entry(message["logical_timestamp"], "SEND",
                        {"peer": peer, "type": message["type"], "message_id": message["id"]},
                        peer=peer, format=fmt, bytes=len(wire),
                        message=message, wire=wire.decode("utf-8", "replace"))

    def recv(self, peer: str, wire: bytes, message: dict, fmt: str) -> None:
        with self.event_lock:
            # Reject unstamped/invalid frames rather than silently inventing a
            # timestamp. The update happens before application dispatch.
            timestamp = self.clock.receive(message.get("logical_timestamp"))
            self._entry(timestamp, "RECV",
                        {"peer": peer, "type": message["type"], "message_id": message["id"],
                         "received_timestamp": message["logical_timestamp"]},
                        peer=peer, format=fmt, bytes=len(wire),
                        wire=wire.decode("utf-8", "replace"), message=message)

    def event(self, event: str, details: dict | None = None, **legacy) -> None:
        """Record a local application transition; increment before the event."""
        with self.event_lock:
            self._entry(self.clock.tick(), event, details or {}, **legacy)

    def info(self, note: str, **extra) -> None:
        self.event("INFO", {"note": note, **extra}, note=note, **extra)
