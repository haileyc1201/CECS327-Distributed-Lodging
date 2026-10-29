"""P2P lookup + discovery demo (UNG-91..94): peers start, the Catalog publishes its
listings into the ring, and a client discovers a listing through a hop-by-hop lookup.

Run from the repository root:  python -m src.communication.p2p_demo
Hop entries are also in logs/messages.jsonl (event INFO, note "LOOKUP hop=...").
"""
from __future__ import annotations

import os

os.environ.setdefault("COMM_QUIET", "1")  # messages still go to logs/messages.jsonl

from .keymap import key_id, listing_key, ownership_table  # noqa: E402
from .lookup import LookupNode  # noqa: E402
from .p2p_catalog import CatalogPeer  # noqa: E402
from .p2p_client import discover_listing  # noqa: E402
from .services import load_properties  # noqa: E402

NAMES = [f"peer-{c}" for c in "ABCDEFGH"]


def main() -> None:
    nodes = [LookupNode(n, port=6400 + i).start() for i, n in enumerate(NAMES, 1)]
    catalog = None
    try:
        for n in nodes[1:]:
            n.join(nodes[0].host, nodes[0].port)
        for _ in range(2):
            for n in nodes:
                n.stabilize()
        ring = sorted(nodes, key=lambda n: n.id)
        print("--- ring (by position):  " + "  ".join(f"{n.name}@{n.id}" for n in ring))

        listings = load_properties()
        keys = [listing_key(p["id"]) for p in listings]
        peers = [n.me for n in nodes]
        print("\n--- UNG-91 who is responsible (key -> successor of its hash)")
        for k, owner in ownership_table(keys, peers).items():
            print(f"  {k:<13} kid={key_id(k):>5} -> {owner}")

        print("\n--- UNG-93 catalog-peer joins and publishes every listing at startup")
        catalog = CatalogPeer(port=6499)
        placed = catalog.start_and_publish((nodes[0].host, nodes[0].port), listings)
        for k, r in placed.items():
            print(f"  {k:<13} stored at {r['owner']:<12} after {r['hops']} hop(s), route {' -> '.join(r['path'])}")
        for n in nodes + [catalog]:
            n.stabilize()

        print("\n--- UNG-92/94 client asks one peer; LOOKUP is forwarded hop by hop")
        for p in listings:
            owner = placed[listing_key(p["id"])]["owner"]
            idx = next(i for i, n in enumerate(ring) if n.name == owner) if owner in NAMES else 0
            start = ring[(idx + 1) % len(ring)]  # the peer just past the owner: farthest away on the ring
            r = discover_listing(p["id"], start.host, start.port)
            print(f"  client -> {start.name}: {'FOUND' if r['found'] else 'NOT FOUND'} {r['listing']}")
            print(f"     owner={r['owner']} hops={r['hops']} route={' -> '.join(r['path'])}")
        r = discover_listing(999, ring[0].host, ring[0].port)
        print(f"  client -> {ring[0].name}: listing 999 -> {'FOUND' if r['found'] else 'NOT_FOUND'} at {r['owner']} "
              f"after {r['hops']} hop(s)")
    finally:
        for n in nodes + ([catalog] if catalog else []):
            n.stop()


if __name__ == "__main__":
    main()
