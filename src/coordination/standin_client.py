"""Real child client for the replaceable coordinator failure demo.

The exclusive marker is an ASSERTION, not an alternate lock: overlap immediately
fails the test, rather than blocking/retrying an incorrectly granted client.
The shared ledger is written only while the coordinator grant is held.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

from src.communication.msglog import MessageLogger
from src.communication.signal_file import read_signal, write_signal
from .standin_coordinator import NET_ERRORS, request


def call_live(peers: list[dict], kind: str, body: dict, logger: MessageLogger) -> dict:
    for peer in sorted(peers, key=lambda item: item["priority"], reverse=True):
        try:
            reply = request(peer, kind, body, logger)
            if reply.get("status") != "REDIRECT":
                return reply
        except NET_ERRORS:
            pass
    return {"status": "RETRY"}


def run_client(name: str, peers: list[dict], directory: Path, hold: bool, timeout: float = 30) -> None:
    logger = MessageLogger(name)
    body = {"client": name, "request_id": uuid.uuid4().hex}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = call_live(peers, "REQUEST", body, logger)
        if reply.get("status") == "GRANT":
            token = reply["token"]
            break
        if reply.get("status") == "DENIED":
            logger.event("CLIENT_WAITING", {"holder": reply["holder"]})
            write_signal(directory / f"{name}.waiting.json", reply, logger, "control.waiting")
        time.sleep(0.05)
    else:
        raise TimeoutError(f"{name} did not acquire the lock")

    active = directory / "critical-section.active"
    # O_EXCL is only a detector: a second granted entrant fails, never waits.
    fd = os.open(active, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(name)
    entered = time.monotonic()
    try:
        logger.event("CS_ENTER", {"client": name, "token": token})
        write_signal(directory / f"{name}.entered.json", {"client": name, "token": token}, logger, "control.entered")
        if hold:
            release = directory / f"{name}.release"
            while not release.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("holder was never told to leave the critical section")
                time.sleep(0.02)
            read_signal(release, logger)
        else:
            time.sleep(0.15)  # nonzero CS duration for the exclusion trace
        with (directory / "shared-resource.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"client": name, "token": token, "operation": "protected ledger append"}) + "\n")
        logger.event("CS_EXIT", {"client": name, "token": token})
        exited = time.monotonic()
    finally:
        active.unlink()

    body["token"] = token
    while time.monotonic() < deadline:
        if call_live(peers, "RELEASE", body, logger).get("status") == "RELEASED":
            logger.event("CLIENT_RELEASE_CONFIRMED", {"token": token})
            write_signal(directory / f"{name}.interval.json",
                         {"client": name, "enter": entered, "exit": exited, "token": token}, logger, "control.interval")
            return
        time.sleep(0.05)
    raise TimeoutError(f"{name} could not release its grant after failover")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--peers", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    run_client(args.name, read_signal(args.peers, MessageLogger(args.name))["peers"], args.directory, args.hold)


if __name__ == "__main__":
    main()
