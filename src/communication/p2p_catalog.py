"""Publish room listings from the Catalog into the overlay (UNG-93, parent UNG-80).

The Catalog's listings (data/properties.json, the same file ``PropertyNode`` serves)
are stored in the P2P ring at startup: a catalog peer joins the ring, and for each
listing it routes a LOOKUP to the peer responsible for ``listing:<id>`` (keymap.py)
and stores the listing there with ``ring.store``. The owner replicates it to its
successor, so a single crash does not lose a listing.

Run a catalog peer that joins an existing ring and publishes on startup:

    python -m src.communication.p2p_catalog 127.0.0.1 6301        # bootstrap peer host port
"""
from __future__ import annotations

import sys
import time

from .keymap import listing_key
from .lookup import LookupNode
from .services import load_properties

CATALOG_PEER = "catalog-peer"


def publish_listings(node: LookupNode, listings: list[dict] | None = None) -> dict[str, dict]:
    """Store every listing under its key at the responsible peer. Returns {key: lookup reply}."""
    listings = load_properties() if listings is None else listings
    placed = {}
    for listing in listings:
        key = listing_key(listing["id"])
        found = node.put_routed(key, listing)
        node.logger.info(f"PUBLISH {key} ({listing.get('name', '')}) -> {found['owner']} after {found['hops']} hop(s)",
                         publish={"key": key, "owner": found["owner"], "hops": found["hops"]})
        placed[key] = found
    node.logger.info(f"PUBLISH done: {len(placed)} listing(s) in the overlay")
    return placed


class CatalogPeer(LookupNode):
    """A ring peer next to the Catalog that publishes all listings when it starts."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, name: str = CATALOG_PEER):
        super().__init__(name, host, port)

    def start_and_publish(self, bootstrap: tuple[str, int] | None = None,
                          listings: list[dict] | None = None) -> dict[str, dict]:
        self.start()
        if bootstrap:
            self.join(*bootstrap)
        return publish_listings(self, listings)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print(__doc__)
        sys.exit(2)
    peer = CatalogPeer(port=int(argv[2]) if len(argv) > 2 else 0)
    placed = peer.start_and_publish((argv[0], int(argv[1])))
    for key, r in placed.items():
        print(f"{key:<14} -> {r['owner']} ({r['hops']} hops)")
    try:
        while True:
            time.sleep(2)
            peer.stabilize()
    except KeyboardInterrupt:
        peer.leave()
        peer.stop()


if __name__ == "__main__":
    main(sys.argv[1:])
