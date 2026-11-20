"""Logical clocks + total ordering across real processes (UNG-100 / UNG-101).

    python3 -m src.communication.clock_demo --output logs/milestone4-demo

Starts three ring/lookup peers as separate OS processes, stores a listing and
looks it up through the ring from a fourth logical node (``clock-client``). Every
frame carries the sender's Lamport stamp ``lc`` (transport.py), every node writes
its own log (``nodes/<node>.jsonl``, msglog.py) and ``merge_logs`` merges them into
one ``(lc, node)``-ordered log. The output directory must not already exist.
Election, mutual exclusion and failure recovery are in coordination_demo.py and
failure_test.py.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .lookup import LookupNode, lookup_via
from .merge_logs import check_causality, format_table, merge_logs
from .msglog import MessageLogger
from .signal_file import read_signal, write_signal
from .ring import RingClient

ROOT = Path(__file__).resolve().parents[2]


def worker(name: str, ready: Path, bootstrap: int | None) -> None:
    node = LookupNode(name).start()
    try:
        if bootstrap is not None:
            node.join("127.0.0.1", bootstrap)
        write_signal(ready, {"name": name, "port": node.port}, node.logger, "control.ready")
        threading.Event().wait()
    finally:
        node.stop()


def wait_ready(process: subprocess.Popen, path: Path, logger: MessageLogger, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"node exited with status {process.returncode}; see process output")
        if path.exists():
            try:
                return read_signal(path, logger)
            except json.JSONDecodeError:
                pass  # worker is still writing readiness
        time.sleep(0.02)
    raise TimeoutError(f"node did not become ready: {path.name}")


def capture(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, "COMM_QUIET": "1", "COMM_LOG_FILE": str(output / "messages.jsonl"),
           "COMM_NODE_LOG_DIR": str(output / "nodes")}
    processes, streams, peers = [], [], []
    previous = {key: os.environ.get(key) for key in ("COMM_QUIET", "COMM_LOG_FILE", "COMM_NODE_LOG_DIR")}
    os.environ.update({key: env[key] for key in previous})
    logger = MessageLogger("clock-client")
    try:
        for name in ("clock-A", "clock-B", "clock-C"):
            ready = output / f"{name}.ready.json"
            command = [sys.executable, "-m", "src.communication.clock_demo", "--worker", name,
                       "--ready", str(ready)]
            if peers:
                command += ["--bootstrap", str(peers[0]["port"])]
            stream = (output / f"{name}.out").open("w", encoding="utf-8")
            streams.append(stream)
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
            processes.append(process)
            peers.append(wait_ready(process, ready, logger))
        client = RingClient("clock-client", [("127.0.0.1", peer["port"]) for peer in peers])
        listing = {"property_id": 101, "name": "Long Beach Apartment"}
        owner = client.put("listing:101", listing)
        result = lookup_via("127.0.0.1", peers[0]["port"], "listing:101", requester="clock-client")
        if result["status"] != "FOUND" or result["value"] != listing:
            raise AssertionError(f"lookup did not return the stored listing: {result}")
        summary = {"kind": "real-process clock/ordering capture, not a recovery test", "nodes": len(peers),
                   "owner": owner, "lookup_path": result["path"], "hops": result["hops"]}
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in streams:
            stream.close()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    events = merge_logs([output / "nodes"], output / "ordered.jsonl")
    summary["events"] = len(events)
    summary["causal_pairs_checked"] = check_causality(events)
    summary["final_clock"] = {node: max(e["lc"] for e in events if e["node"] == node)
                              for node in sorted({e["node"] for e in events})}
    summary["message_types"] = sorted({event["message"]["type"] for event in events if "message" in event})
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("logs/milestone4-demo"))
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--ready", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--bootstrap", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.ready is None:
            parser.error("worker requires --ready")
        worker(args.worker, args.ready, args.bootstrap)
    else:
        summary = capture(args.output)
        events = [json.loads(line) for line in (args.output / "ordered.jsonl").read_text().splitlines()]
        print(f"3 ring peers (separate processes) + clock-client; owner of listing:101 = {summary['owner']}")
        print(f"lookup path {' -> '.join(summary['lookup_path'])} ({summary['hops']} hops), listing FOUND")
        print(f"merged {summary['events']} events from {len(summary['final_clock'])} per-node logs "
              f"into {args.output / 'ordered.jsonl'}")
        print(f"checked {summary['causal_pairs_checked']} send/receive pairs: every RECV has a larger lc "
              f"than its SEND (happened-before preserved)")
        print("final Lamport clock per node:", ", ".join(f"{k}={v}" for k, v in summary["final_clock"].items()))
        print("\nfirst messages of the run in total order (lc, node):")
        print(format_table([e for e in events if e["event"] in ("SEND", "RECV")], 18))


if __name__ == "__main__":
    main()
