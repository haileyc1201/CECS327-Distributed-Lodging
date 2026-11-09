"""Lamport-stamped local file IPC for process-demo control, not a new protocol.

Readiness and release signals also communicate causality. Stamping only TCP
would let a total-ordered log place the driver's kill before the holder entered,
or its CS exit before recovery. These files use the SAME envelope and logger
clock rules as TCP. Atomic rename prevents observers reading partial frames.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .codec import make_envelope, marshal, unmarshal
from .msglog import MessageLogger


def write_signal(path: Path, payload: dict, logger: MessageLogger, kind: str = "control.signal") -> None:
    with logger.event_lock:
        message = make_envelope(kind, logger.node, payload, receiver=path.name)
        message["logical_timestamp"] = logger.clock.send()
        wire = marshal(message)
        logger.send("file:" + path.name, message, wire, "json")
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(wire)
                stream.flush()
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)


def read_signal(path: Path, logger: MessageLogger) -> dict:
    wire = path.read_bytes()
    message = unmarshal(wire)
    logger.recv("file:" + path.name, wire, message, "json")
    return message["payload"]
