"""UNG-92/93/94: hop-by-hop LOOKUP, catalog publish, client discovery.

Run from the repository root:   python -m unittest tests.test_p2p_lookup -v
"""
import json
import os
import tempfile
import unittest

os.environ["COMM_QUIET"] = "1"
_TMP = tempfile.mkdtemp()
os.environ["COMM_LOG_FILE"] = os.path.join(_TMP, "messages.jsonl")

from src.communication.keymap import listing_key, responsible_peer  # noqa: E402
from src.communication.lookup import LookupNode  # noqa: E402
from src.communication.p2p_catalog import CatalogPeer  # noqa: E402
from src.communication.p2p_client import discover_listing  # noqa: E402
from src.communication.services import load_properties  # noqa: E402


class P2PLookupTest(unittest.TestCase):
    def setUp(self):
        self.nodes = [LookupNode(f"peer-{c}").start() for c in "ABCDEF"]
        for n in self.nodes[1:]:
            n.join(self.nodes[0].host, self.nodes[0].port)
        self.settle()

    def tearDown(self):
        for n in self.nodes:
            n.stop()

    def settle(self):
        for _ in range(2):
            for n in self.nodes:
                n.stabilize()

    def test_lookup_reaches_responsible_peer_hop_by_hop(self):
        peers = [n.me for n in self.nodes]
        for i in range(30):
            key = f"room-{i}"
            owner = responsible_peer(key, peers)["name"]
            for start in self.nodes:
                r = start.lookup(key)
                self.assertEqual(r["owner"], owner)
                self.assertEqual(r["hops"], len(r["path"]) - 1)
                self.assertEqual(r["path"][0], start.name)
                self.assertEqual(r["path"][-1], owner)
        some_multi_hop = any(n.lookup(f"room-{i}")["hops"] >= 2 for n in self.nodes for i in range(30))
        self.assertTrue(some_multi_hop)

    def test_each_hop_is_logged_with_hop_count(self):
        r = self.nodes[0].lookup("room-7")
        with open(os.environ["COMM_LOG_FILE"], encoding="utf-8") as fh:
            hops = [e for e in map(json.loads, fh) if e.get("lookup", {}).get("key") == "room-7"]
        self.assertEqual([e["lookup"]["hop"] for e in hops[-(r["hops"] + 1):]], list(range(r["hops"] + 1)))
        self.assertEqual(hops[-1]["lookup"]["action"], "answer")

    def test_catalog_publish_and_client_discovery(self):
        catalog = CatalogPeer()
        self.nodes.append(catalog)
        placed = catalog.start_and_publish((self.nodes[0].host, self.nodes[0].port))
        self.settle()
        listings = load_properties()
        peers = [n.me for n in self.nodes]
        for p in listings:
            key = listing_key(p["id"])
            owner = responsible_peer(key, peers)["name"]
            self.assertEqual(placed[key]["owner"], owner)
            for start in self.nodes:
                r = discover_listing(p["id"], start.host, start.port)
                self.assertTrue(r["found"])
                self.assertEqual(r["listing"], p)
                self.assertEqual(r["owner"], owner)
        self.assertFalse(discover_listing(999, self.nodes[0].host, self.nodes[0].port)["found"])

    def test_discovery_survives_owner_crash(self):
        catalog = CatalogPeer()
        self.nodes.append(catalog)
        placed = catalog.start_and_publish((self.nodes[0].host, self.nodes[0].port))
        self.settle()
        key = listing_key(101)
        victim = next(n for n in self.nodes if n.name == placed[key]["owner"])
        victim.stop()
        self.nodes.remove(victim)
        self.settle()
        r = discover_listing(101, self.nodes[0].host, self.nodes[0].port)
        self.assertTrue(r["found"])
        self.assertNotEqual(r["owner"], victim.name)


if __name__ == "__main__":
    unittest.main()
