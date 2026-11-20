"""Tom's event-ordering tests (UNG-101 / UNG-110 / UNG-111): merge_logs on the logs main's nodes write."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.communication.merge_logs import check_causality, format_table, merge_logs, ordered_events
from src.communication.node import make_cluster


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_log(self, name, entries):
        path = self.directory / name
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
        return path

    @staticmethod
    def event(lc, node):
        return {"ts": "2026-11-19T00:00:00.000Z", "lc": lc, "node": node, "event": "INFO", "note": "x"}

    def test_lamport_time_then_node_name_independent_of_input_order(self):
        a = self.write_log("a.jsonl", [self.event(10, "node-a"), self.event(2, "node-a")])
        b = self.write_log("b.jsonl", [self.event(2, "node-b"), self.event(1, "node-b")])
        expected = [(1, "node-b"), (2, "node-a"), (2, "node-b"), (10, "node-a")]
        for paths in ([a, b], [b, a], [self.directory]):
            self.assertEqual([(e["lc"], e["node"]) for e in ordered_events(paths)], expected)

    def test_merge_script_writes_parseable_ordered_log(self):
        source = self.write_log("source.jsonl", [self.event(9, "b"), self.event(1, "a")])
        output = self.directory / "ordered.jsonl"
        process = subprocess.run([sys.executable, "-m", "src.communication.merge_logs", str(source),
                                  "--output", str(output), "--table", "5"], text=True, capture_output=True,
                                 check=True)
        self.assertIn("Merged 2 events", process.stdout)
        self.assertIn("LC | node", process.stdout)
        self.assertEqual([json.loads(line)["lc"] for line in output.read_text().splitlines()], [1, 9])

    def test_rejects_duplicate_keys_and_input_output_overlap(self):
        source = self.write_log("source.jsonl", [self.event(1, "a")])
        with self.assertRaisesRegex(ValueError, "duplicate event key"):
            ordered_events([source, source])
        with self.assertRaisesRegex(ValueError, "overwrite"):
            merge_logs([source], source)

    def test_malformed_logs_report_source_line(self):
        bad_entries = ({}, {**self.event(1, "a"), "lc": True}, {**self.event(1, "a"), "lc": -1},
                       {**self.event(1, "a"), "node": ""}, {**self.event(1, "a"), "lc": "2"},
                       {**self.event(1, "a"), "event": ""}, [1, 2])
        for event in bad_entries:
            source = self.write_log("bad.jsonl", [event])
            with self.assertRaisesRegex(ValueError, "bad.jsonl:1"):
                ordered_events([source])
        source.write_text("{truncated", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bad.jsonl:1"):
            ordered_events([source])

    def test_empty_logs_are_not_successful_output(self):
        source = self.write_log("empty.jsonl", [])
        with self.assertRaisesRegex(ValueError, "no events"):
            ordered_events([source])

    def test_causality_check_catches_a_receive_before_its_send(self):
        send = {**self.event(5, "a"), "event": "SEND", "message": {"id": "m1", "lc": 5}}
        recv = {**self.event(3, "b"), "event": "RECV", "message": {"id": "m1", "lc": 5}}
        with self.assertRaises(ValueError):
            check_causality([recv, send])
        self.assertEqual(check_causality([send, {**recv, "lc": 6}]), 1)


class RealNodeLogTests(unittest.TestCase):
    """Per-node logs from main's CoordinationNodes merge into one causally consistent order."""

    def test_cluster_logs_merge_in_causal_order(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            with patch.dict(os.environ, {"COMM_LOG_FILE": str(d / "messages.jsonl"),
                                         "COMM_NODE_LOG_DIR": str(d / "nodes"), "COMM_QUIET": "1"}):
                nodes = make_cluster([("ord-A", 1), ("ord-B", 2), ("ord-C", 3)])
                try:
                    nodes[0].election.start_election()
                    nodes[1].mutex.acquire()
                    nodes[1].mutex.release()
                finally:
                    for n in nodes:
                        n.stop()
                events = merge_logs([d / "nodes"], d / "ordered.jsonl")
            self.assertEqual({p.stem for p in (d / "nodes").glob("*.jsonl")}, {"ord-A", "ord-B", "ord-C"})
            keys = [(e["lc"], e["node"]) for e in events]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(len(keys), len(set(keys)))
            self.assertGreater(check_causality(events), 10)
            won = next(e for e in events if e.get("election", {}).get("action") == "won")
            accepts = [e for e in events if e.get("election", {}).get("action") == "accept"]
            self.assertEqual(won["node"], "ord-C")
            self.assertEqual(len(accepts), 2)
            self.assertIn("ord-B", format_table(events))


if __name__ == "__main__":
    unittest.main()
