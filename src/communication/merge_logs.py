"""Merge per-node JSONL event logs into one total-ordered log (UNG-101 / UNG-111).

    python3 -m src.communication.merge_logs logs/nodes -o logs/ordered.jsonl

Input is what the nodes actually write (msglog.py): one entry per line with the
Lamport time ``lc`` (integer), the node name ``node`` and the ``event`` kind
(SEND / RECV / INFO / ...). Order is ``(lc, node)``: Lamport time first, ties
broken by node name, NOT wall-clock time. This is a total order that is
consistent with happened-before (if a -> b then lc(a) < lc(b)).

Use either the per-node files or the aggregate messages.jsonl, never both.
Duplicate ``(lc, node)`` keys are errors: every node must have a unique name and
its clock never repeats a value.
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
                    if not isinstance(event, dict):
                        raise ValueError("entry must be a JSON object")
                    timestamp, node = event["lc"], event["node"]
                    if type(timestamp) is not int or timestamp < 0:
                        raise ValueError("lc must be a nonnegative integer")
                    if not isinstance(node, str) or not node:
                        raise ValueError("node must be a nonempty string")
                    if not isinstance(event["event"], str) or not event["event"]:
                        raise ValueError("event must be a nonempty string")
                    key = (timestamp, node)
                    if key in seen:
                        raise ValueError(f"duplicate event key {key}; check duplicate inputs/node ids")
                    seen.add(key)
                    events.append(event)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{path}:{number}: {exc}") from exc
    if not events:
        raise ValueError("input logs contain no events")
    return sorted(events, key=order_key)


def order_key(event: dict) -> tuple[int, str]:
    """The total order: Lamport time, then node name."""
    return event["lc"], event["node"]


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


def check_causality(events: list[dict]) -> int:
    """Every RECV must come after its SEND in the merged order (lc strictly larger).

    Pairs are matched by (message id, stamp); returns the number of pairs checked.
    """
    sends = {(e["message"].get("id"), e["message"].get("lc")): e for e in events
             if e["event"] == "SEND" and isinstance(e.get("message"), dict)}
    checked = 0
    for e in events:
        if e["event"] != "RECV" or not isinstance(e.get("message"), dict):
            continue
        sent = sends.get((e["message"].get("id"), e["message"].get("lc")))
        if sent is None:              # sender outside the captured logs (e.g. a test client)
            continue
        if order_key(e) <= order_key(sent):
            raise ValueError(f"RECV {order_key(e)} is not after its SEND {order_key(sent)}")
        checked += 1
    return checked


def peer_of(event: dict) -> str:
    """Name of the other node of a SEND/RECV (from the envelope), else the event's own peer field."""
    msg = event.get("message") if isinstance(event.get("message"), dict) else {}
    if event["event"] == "SEND":
        return msg.get("receiver") or event.get("peer", "")
    if event["event"] == "RECV":
        return msg.get("sender") or event.get("peer", "")
    return event.get("peer", "")


def describe(event: dict) -> str:
    msg = event.get("message") if isinstance(event.get("message"), dict) else {}
    if msg:
        return msg.get("type", "")
    return event.get("note") or event.get("msg_type") or event.get("key") or ""


def format_table(events: list[dict], limit: int | None = None) -> str:
    """Readable ``LC | node | event | peer | detail`` view of an ordered log."""
    rows = events if limit is None else events[:limit]
    width = max([len(e["node"]) for e in rows] + [4])
    ew = max([len(e["event"]) for e in rows] + [5])
    lines = [f"{'LC':>4} | {'node':<{width}} | {'event':<{ew}} | {'peer':<16} | detail",
             f"{'-' * 4}-+-{'-' * width}-+-{'-' * ew}-+-{'-' * 16}-+-{'-' * 40}"]
    for e in rows:
        lines.append(f"{e['lc']:>4} | {e['node']:<{width}} | {e['event']:<{ew}} | {peer_of(e)[:16]:<16} | "
                     f"{describe(e)[:90]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--table", type=int, metavar="N", help="also print N ordered events as a table")
    parser.add_argument("--since", type=int, default=0, metavar="LC", help="table starts at this Lamport time")
    args = parser.parse_args()
    try:
        events = merge_logs(args.inputs, args.output)
        pairs = check_causality(events)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"merge failed: {exc}\n")
    print(f"Merged {len(events)} events from {len({e['node'] for e in events})} nodes into {args.output}")
    print(f"Order: (lc, node). Checked {pairs} send/receive pairs: every receive is ordered after its send.")
    if args.table:
        print(format_table([e for e in events if e["lc"] >= args.since], args.table))


if __name__ == "__main__":
    main()
