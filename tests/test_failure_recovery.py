"""Tom's failure test (UNG-105 / UNG-120..122) on main's Bully election and Ricart-Agrawala mutex.

The integration test runs the real scenario: six OS processes, the leader is
SIGKILLed inside the critical section, node-D is re-elected and the shared
resource stays consistent. Nothing is mocked.
"""
import json
import tempfile
import unittest
from pathlib import Path

from src.communication.failure_test import check_intervals, run_failure_test
from src.communication.merge_logs import check_causality


class ExclusionAssertions(unittest.TestCase):
    def test_overlap_and_missing_contender_rejected(self):
        for intervals in ([{"client": "h", "enter": 1, "exit": 4}, {"client": "c", "enter": 2, "exit": 5}],
                          [{"client": "h", "enter": 1, "exit": 2}],
                          [{"client": "h", "enter": 1, "exit": 2}, {"client": "c", "enter": 3, "exit": float("nan")}]):
            with self.assertRaises(AssertionError):
                check_intervals(intervals, "h")
        check_intervals([{"client": "h", "enter": 1, "exit": 2}, {"client": "c", "enter": 2, "exit": 3}], "h")


class RealFailureIntegration(unittest.TestCase):
    def test_kill_leader_in_critical_section_reelect_and_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture"
            result = run_failure_test(output, updates=2)
            self.assertEqual(result["status"], "passed")
            self.assertEqual((result["old_leader"], result["new_leader"]), ("node-E", "node-D"))
            self.assertEqual(result["leader_returncode"], -9, "injected failure must really be SIGKILL")
            self.assertEqual(result["resource"]["value"], 5)
            self.assertEqual(result["resource"]["violations"], [])

            nodes = {p.stem for p in (output / "nodes").glob("*.jsonl")}
            self.assertTrue({"node-A", "node-B", "node-C", "node-D", "node-E", "failure-driver",
                             "shared-resource"} <= nodes)
            events = [json.loads(line) for line in (output / "ordered.jsonl").read_text().splitlines()]
            keys = [(e["lc"], e["node"]) for e in events]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(len(keys), len(set(keys)))
            self.assertGreater(check_causality(events), 50)

            def first(pred):
                return next(e for e in events if pred(e))
            mutex = lambda e, action, node: e.get("mutex", {}).get("action") == action and e["node"] == node
            entered = first(lambda e: mutex(e, "enter", "node-E"))
            observed = first(lambda e: e["event"] == "CRITICAL_SECTION_OBSERVED")
            killed = first(lambda e: e["event"] == "LEADER_KILL_REQUESTED")
            # node-E enters -> its status reply -> driver observes -> kill: a causal chain
            self.assertLess((entered["lc"], entered["node"]), (observed["lc"], observed["node"]))
            self.assertLess(observed["lc"], killed["lc"])
            self.assertFalse(any(mutex(e, "exit", "node-E") for e in events), "node-E never released")
            for name in ("node-C", "node-D"):
                self.assertTrue(any(e.get("mutex", {}).get("action") == "peer-down" and e["node"] == name
                                    and e["mutex"]["peer"] == "node-E" for e in events))
            self.assertEqual(first(lambda e: e.get("election", {}).get("action") == "won"
                                   and e["node"] == "node-D")["election"]["leader"], "node-D")
            self.assertTrue(any(e["event"] == "MUTUAL_EXCLUSION_VERIFIED" for e in events))
            self.assertTrue((output / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
