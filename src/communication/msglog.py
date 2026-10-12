"""ISO-8601 timestamped message logging.

Every send and receive is written as one JSON object per line (JSON Lines) to
``logs/messages.jsonl`` (override with the COMM_LOG_FILE environment variable)
and echoed to stdout in a readable form. Each entry records the message both
*before* marshalling (the dict) and *after* (the wire text), which documents
the marshalling / unmarshalling step.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .codec import now_iso

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "logs" / "messages.jsonl"
_lock = threading.Lock()


def log_path() -> Path:
    return Path(os.environ.get("COMM_LOG_FILE", DEFAULT_LOG))


class MessageLogger:
    def __init__(self, node: str, quiet: bool | None = None):
        self.node = node
        self.quiet = bool(os.environ.get("COMM_QUIET")) if quiet is None else quiet

    def _write(self, entry: dict) -> None:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, separators=(",", ":"))
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if not self.quiet:
            ev = entry["event"]
            msg = entry.get("message") or {}
            arrow = "->" if ev == "SEND" else "<-" if ev == "RECV" else "**"
            print(f"{entry['ts']} [{self.node}] {ev:<5} {arrow} {entry.get('peer','')} "
                  f"type={msg.get('type', '')} id={msg.get('id', '')} "
                  f"fmt={entry.get('format', '')} bytes={entry.get('bytes', '')} "
                  f"{entry.get('note', '')}", flush=True)

    def send(self, peer: str, message: dict, wire: bytes, fmt: str) -> None:
        self._write({"ts": now_iso(), "node": self.node, "event": "SEND", "peer": peer,
                     "format": fmt, "bytes": len(wire),
                     "message": message,                      # before marshalling
                     "wire": wire.decode("utf-8", "replace")})  # after marshalling

    def recv(self, peer: str, wire: bytes, message: dict, fmt: str) -> None:
        self._write({"ts": now_iso(), "node": self.node, "event": "RECV", "peer": peer,
                     "format": fmt, "bytes": len(wire),
                     "wire": wire.decode("utf-8", "replace"),  # before unmarshalling
                     "message": message})                      # after unmarshalling

    def info(self, note: str, **extra) -> None:
        self._write({"ts": now_iso(), "node": self.node, "event": "INFO", "note": note, **extra})
