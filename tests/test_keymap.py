"""UNG-91: key to peer mapping.   python -m unittest tests.test_keymap -v"""
import os
import unittest

os.environ.setdefault("COMM_QUIET", "1")

from src.communication.keymap import (is_responsible, key_id, listing_key, ownership_table,  # noqa: E402
                                      responsible_id, responsible_peer)
from src.communication.ring import RING_SIZE, ring_id  # noqa: E402


class KeyMapTest(unittest.TestCase):
    def test_key_hash_is_stable_and_in_range(self):
        self.assertEqual(listing_key(101), "listing:101")
        self.assertEqual(key_id("listing:101"), key_id("listing:101"))
        self.assertEqual(key_id("listing:101"), ring_id("listing:101"))
        for i in range(200):
            self.assertTrue(0 <= key_id(listing_key(i)) < RING_SIZE)

    def test_successor_rule(self):
        ids = [100, 2000, 40000]
        self.assertEqual(responsible_id(50, ids), 100)
        self.assertEqual(responsible_id(100, ids), 100)      # exact hit owns it
        self.assertEqual(responsible_id(101, ids), 2000)
        self.assertEqual(responsible_id(39999, ids), 40000)
        self.assertEqual(responsible_id(40001, ids), 100)    # wraps around
        self.assertEqual(responsible_id(RING_SIZE - 1, ids), 100)

    def test_is_responsible_matches_successor_rule(self):
        ids = sorted([ring_id(f"peer-{c}") for c in "ABCDE"])
        preds = {ids[i]: ids[i - 1] for i in range(len(ids))}
        for n in range(300):
            kid = key_id(listing_key(n))
            owners = [i for i in ids if is_responsible(kid, preds[i], i)]
            self.assertEqual(owners, [responsible_id(kid, ids)])  # exactly one owner
        self.assertTrue(is_responsible(1234, 7, 7))           # alone: owns everything

    def test_responsible_peer_and_table(self):
        peers = [{"name": f"peer-{c}", "id": ring_id(f"peer-{c}")} for c in "ABCD"]
        keys = [listing_key(i) for i in (101, 102, 103)]
        table = ownership_table(keys, peers)
        for k in keys:
            self.assertEqual(table[k], responsible_peer(k, peers)["name"])
        with self.assertRaises(ValueError):
            responsible_id(5, [])


if __name__ == "__main__":
    unittest.main()
