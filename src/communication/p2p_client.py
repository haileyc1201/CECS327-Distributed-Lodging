"""Client search discovers a listing through a peer lookup (UNG-94, parent UNG-80).

The client (or a gateway) knows the address of *any* peer, not where a listing
lives. It sends ``ring.lookup`` for ``listing:<id>`` to that peer; the LOOKUP is
forwarded hop by hop to the responsible peer and the listing comes back through
the lookup reply: "resource discovered via P2P".

    python -m src.communication.p2p_client 101 --peer 127.0.0.1:6303
"""
from __future__ import annotations

import argparse

from .keymap import listing_key
from .lookup import lookup_via


def discover_listing(listing_id, peer_host: str, peer_port: int, requester: str = "client") -> dict:
    """Search for a listing through the overlay. Returns {"found", "listing", "owner", "hops", "path"}."""
    r = lookup_via(peer_host, peer_port, listing_key(listing_id), requester=requester)
    return {"found": r["status"] == "FOUND", "listing": r["value"], "key": r["key"],
            "owner": r["owner"], "hops": r["hops"], "path": r["path"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("listing_id")
    ap.add_argument("--peer", default="127.0.0.1:6301", help="any ring peer, host:port")
    a = ap.parse_args()
    host, port = a.peer.rsplit(":", 1)
    r = discover_listing(a.listing_id, host, int(port))
    route = " -> ".join(r["path"])
    if r["found"]:
        print(f"resource discovered via P2P: {r['listing']}\n  owner={r['owner']} hops={r['hops']} route={route}")
    else:
        print(f"listing {a.listing_id} not in the overlay (asked {r['owner']}, hops={r['hops']}, route={route})")


if __name__ == "__main__":
    main()
