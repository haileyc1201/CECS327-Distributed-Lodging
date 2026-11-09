"""Merge per-node JSONL events in total order (UNG-101 / UNG-111).

    python3 -m src.communication.merge_logs logs/nodes -o logs/ordered.jsonl

Order is (integer Lamport timestamp, string node id), NOT wall-clock time.
Use either per-node files or the aggregate, never both. Duplicate event keys
are errors: each node must have a unique id and strictly increasing clock.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def input_files(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        found = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
        if not found:
            raise ValueError(f"no JSONL files in {path}")
        files.extend(found)
    if not files:
        raise ValueError("at least one input log is required")
    return files


def ordered_events(paths: list[Path]) -> list[dict]:
    events, seen = [], set()
    for path in input_files(paths):
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    timestamp, node = event["timestamp"], event["node_id"]
                    if type(timestamp) is not int or timestamp < 1:
                        raise ValueError("timestamp must be a positive integer")
                    if not isinstance(node, str) or not node:
                        raise ValueError("node_id must be a nonempty string")
                    if not isinstance(event["event"], str) or not event["event"]:
                        raise ValueError("event must be a nonempty string")
                    if not isinstance(event["details"], dict):
                        raise ValueError("details must be an object")
                    key = (timestamp, node)
                    if key in seen:
                        raise ValueError(f"duplicate event key {key}; check duplicate inputs/node ids")
                    seen.add(key)
                    events.append(event)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{path}:{number}: {exc}") from exc
    if not events:
        raise ValueError("input logs contain no events")
    return sorted(events, key=lambda event: (event["timestamp"], event["node_id"]))


def merge_logs(paths: list[Path], output: Path) -> list[dict]:
    files = input_files(paths)
    if output.resolve() in {path.resolve() for path in files}:
        raise ValueError("output must not overwrite an input log")
    events = ordered_events(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        events = merge_logs(args.inputs, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"merge failed: {exc}\n")
    print(f"Merged {len(events)} events from {len({e['node_id'] for e in events})} nodes into {args.output}")


if __name__ == "__main__":
    main()
