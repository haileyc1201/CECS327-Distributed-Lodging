"""Stand-in protocol unit checks plus a REAL six-process failure integration.

Only the unit tests stub replication; no sample output is generated from mocks.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.communication.failure_test import check_intervals, run_failure_test
from src.coordination.standin_adapter import StandinAdapter
from src.coordination.standin_coordinator import StandinCoordinator


class StandinLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.env = patch.dict("os.environ", {"COMM_LOG_FILE": str(directory / "messages.jsonl"),
                                            "COMM_NODE_LOG_DIR": str(directory / "nodes"), "COMM_QUIET": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.node = StandinCoordinator("unit-leader", 3)
        self.addCleanup(self.node.stop)
        self.node.leader_id = self.node.name
        self.replication = patch.object(self.node, "_replicate", return_value=True)
        self.replication.start()
        self.addCleanup(self.replication.stop)

    def test_retry_same_grant_denial_and_stale_release(self):
        holder = {"client": "holder", "request_id": "request-1"}
        granted = self.node._handle("REQUEST", holder)
        self.assertEqual(granted["status"], "GRANT")
        self.assertEqual(self.node._handle("REQUEST", holder), granted)
        self.assertEqual(self.node._handle("REQUEST", {"client": "contender", "request_id": "request-2"})["status"], "DENIED")
        self.assertEqual(self.node._handle("RELEASE", {**holder, "token": "wrong"})["status"], "REJECTED")
        released = self.node._handle("RELEASE", {**holder, "token": granted["token"]})
        self.assertEqual(released["status"], "RELEASED")
        self.assertEqual(self.node._handle("RELEASE", {**holder, "token": granted["token"]}), released)
        self.assertEqual(self.node._handle("REQUEST", {"client": "contender", "request_id": "request-2"})["status"], "GRANT")
        self.assertEqual(self.node._handle("RELEASE", {**holder, "token": granted["token"]})["status"], "RELEASED")
        self.assertEqual(self.node.lock_state["holder"], "contender", "duplicate old release must not clear a newer grant")

    def test_no_grant_without_replication_quorum(self):
        self.node._replicate.return_value = False
        self.assertEqual(self.node._handle("REQUEST", {"client": "holder", "request_id": "request-1"})["status"], "RETRY")

    def test_restore_does_not_clear_a_live_holder(self):
        holder = {"client": "holder", "request_id": "request-1"}
        grant = self.node._handle("REQUEST", holder)
        snapshot = dict(self.node.lock_state)
        successor = StandinCoordinator("unit-successor", 2)
        self.addCleanup(successor.stop)
        successor.peers = {self.node.name: {"name": self.node.name}}
        self.assertEqual(successor._handle("REPLICATE", {"leader": self.node.name, "state": snapshot})["status"], "REPLICATED")
        successor._install_leader(successor.name)
        self.assertEqual(successor.lock_state["token"], grant["token"])
        with patch.object(successor, "_replicate", return_value=True):
            self.assertEqual(successor._handle("REQUEST", holder), grant, "lost GRANT can be retried after failover")
        self.assertEqual(successor._handle("REQUEST", {"client": "other", "request_id": "other"})["status"], "DENIED")


class ExclusionAssertions(unittest.TestCase):
    def test_overlap_and_missing_contender_rejected(self):
        for intervals in ([{"client": "h", "enter": 1, "exit": 4}, {"client": "c", "enter": 2, "exit": 5}],
                          [{"client": "h", "enter": 1, "exit": 2}],
                          [{"client": "h", "enter": 1, "exit": 2}, {"client": "c", "enter": 3, "exit": float("nan")} ]):
            with self.assertRaises(AssertionError):
                check_intervals(intervals, "h")
        check_intervals([{"client": "h", "enter": 1, "exit": 2}, {"client": "c", "enter": 2, "exit": 3}], "h")


class RealFailureIntegration(unittest.TestCase):
    def test_kill_live_leader_restore_holder_then_grant_contender(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture"
            adapter = StandinAdapter()
            result = run_failure_test(adapter, output)
            self.assertEqual(result["status"], "passed")
            self.assertEqual((result["old_leader"], result["new_leader"]), ("standin-3", "standin-2"))
            self.assertTrue(result["recovery"]["holder_still_active"])
            events = [json.loads(line) for line in (output / "ordered.jsonl").read_text().splitlines()]
            kinds = {event["event"] for event in events}
            self.assertTrue({"LEADER_FAILURE_DETECTED", "LOCK_STATE_RESTORED", "LOCK_DENIED", "CS_ENTER",
                             "LOCK_RELEASED", "CONTENDER_BLOCKED_AFTER_FAILOVER"} <= kinds)
            keys = [(event["timestamp"], event["node_id"]) for event in events]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(len(keys), len(set(keys)))
            sends = {(event["message"]["id"], event["message"]["logical_timestamp"]): event for event in events if event["event"] == "SEND"}
            for event in events:
                if event["event"] == "RECV":
                    key = (event["message"]["id"], event["message"]["logical_timestamp"])
                    self.assertIn(key, sends)
                    self.assertGreater(event["timestamp"], key[1])
            self.assertTrue(all(process.poll() is not None for process in adapter.processes.values()))
            self.assertEqual(adapter.processes["standin-3"].returncode, -9, "injected failure must really be SIGKILL")
            entered = next(event for event in events if event["node_id"] == "failure-holder" and event["event"] == "CS_ENTER")
            killed = next(event for event in events if event["event"] == "LEADER_KILL_REQUESTED")
            self.assertLess(entered["timestamp"], killed["timestamp"], "file readiness must preserve causal order")
