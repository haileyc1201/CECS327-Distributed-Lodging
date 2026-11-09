"""Strict event schema, total-order tie breaks, and CLI merge coverage."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.communication.merge_logs import merge_logs, ordered_events


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
    def event(timestamp, node):
        return {"timestamp": timestamp, "node_id": node, "event": "LOCAL", "details": {}}

    def test_timestamp_then_string_node_id_independent_of_input_order(self):
        a = self.write_log("a.jsonl", [self.event(10, "node-a"), self.event(2, "node-a")])
        b = self.write_log("b.jsonl", [self.event(2, "node-b"), self.event(1, "node-b")])
        expected = [(1, "node-b"), (2, "node-a"), (2, "node-b"), (10, "node-a")]
        for paths in ([a, b], [b, a], [self.directory]):
            self.assertEqual([(e["timestamp"], e["node_id"]) for e in ordered_events(paths)], expected)

    def test_merge_script_writes_parseable_ordered_log(self):
        source = self.write_log("source.jsonl", [self.event(9, "b"), self.event(1, "a")])
        output = self.directory / "ordered.jsonl"
        process = subprocess.run([sys.executable, "-m", "src.communication.merge_logs", str(source),
                                  "--output", str(output)], text=True, capture_output=True, check=True)
        self.assertIn("Merged 2 events", process.stdout)
        self.assertEqual([json.loads(line)["timestamp"] for line in output.read_text().splitlines()], [1, 9])

    def test_rejects_duplicate_keys_and_input_output_overlap(self):
        source = self.write_log("source.jsonl", [self.event(1, "a")])
        with self.assertRaisesRegex(ValueError, "duplicate event key"):
            ordered_events([source, source])
        with self.assertRaisesRegex(ValueError, "overwrite"):
            merge_logs([source], source)

    def test_malformed_logs_report_source_line(self):
        bad_entries = ({}, {**self.event(1, "a"), "timestamp": True}, {**self.event(1, "a"), "details": []},
                       {**self.event(1, "a"), "node_id": ""}, {**self.event(1, "a"), "timestamp": "2"})
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
