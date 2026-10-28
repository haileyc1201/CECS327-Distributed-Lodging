"""Ring overlay demo: 5 peers join, one leaves gracefully, one crashes.

Run from the repository root:  python -m src.communication.ring_demo
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("COMM_QUIET", "1")  # messages still go to logs/messages.jsonl

from .ring import RingNode, ring_id  # noqa: E402

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"


def show(title: str, nodes: list[RingNode]) -> None:
    print(f"\n--- {title}")
    for n in sorted(nodes, key=lambda n: n.id):
        s = n.state()
        print(f"  {s['name']:<7} id={s['id']:>5}  pred={s['pred']:<7} succs={s['succs']}")
        print(f"          keys={s['keys']}  replicas={s['replicas']}")


def stabilize_all(nodes: list[RingNode]) -> None:
    for _ in range(2):  # two rounds so successor lists settle
        for n in nodes:
            n.stabilize()


def check_all_keys(node: RingNode, keys: list[str]) -> None:
    missing = [k for k in keys if not node.get(k)["found"]]
    print(f"  lookup of {len(keys)} keys via {node.name}: {'all found' if not missing else 'MISSING ' + str(missing)}")


def main() -> None:
    nodes = [RingNode(f"peer-{c}", port=6300 + i).start() for i, c in enumerate("ABCDE", 1)]
    try:
        first = nodes[0]
        for n in nodes[1:]:
            n.join(first.host, first.port)             # everyone bootstraps through peer-A
        stabilize_all(nodes)
        show("ring after 5 joins (ordered by ring position)", nodes)

        props = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        keys = [str(p["id"]) for p in props]
        for i, p in enumerate(props):
            nodes[i % len(nodes)].put(str(p["id"]), p)  # any peer can store; it routes to the owner
        show("after storing every property (keys + replicas on the successor)", nodes)

        leaver = sorted(nodes, key=lambda n: n.id)[1]
        print(f"\n=== {leaver.name} leaves gracefully (hands its keys to its successor)")
        leaver.leave()
        leaver.stop()
        nodes.remove(leaver)
        stabilize_all(nodes)
        show(f"after {leaver.name} left", nodes)
        check_all_keys(nodes[0], keys)

        victim = sorted(nodes, key=lambda n: n.id)[2]
        print(f"\n=== {victim.name} crashes (no goodbye)")
        victim.stop()
        nodes.remove(victim)
        for n in nodes:
            repaired = n.stabilize()
            if repaired:
                print(f"  {n.name} heartbeat timed out on {repaired}; neighbours repaired")
        stabilize_all(nodes)
        show(f"after {victim.name} crashed", nodes)
        check_all_keys(nodes[0], keys)
    finally:
        for n in nodes:
            n.stop()


if __name__ == "__main__":
    main()
