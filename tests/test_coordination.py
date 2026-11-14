"""Tests for logical clocks, Bully election, Ricart-Agrawala mutual exclusion and the shared resource.

Run from the repository root:   python -m unittest tests.test_coordination -v
"""
import json
import os
import tempfile
import threading
import time
import unittest

os.environ["COMM_QUIET"] = "1"
_TMP = tempfile.mkdtemp()
os.environ["COMM_LOG_FILE"] = os.path.join(_TMP, "messages.jsonl")

from src.communication.clock import LamportClock  # noqa: E402
from src.communication.node import CoordinationNode, make_cluster  # noqa: E402
from src.communication.resource import SharedResource, update_resource  # noqa: E402
from src.communication.rpc import RPCClient  # noqa: E402


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def log_entries():
    with open(os.environ["COMM_LOG_FILE"], encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


class TC1_LamportClock(unittest.TestCase):
    def test_rules(self):
        c = LamportClock()
        self.assertEqual(c.tick(), 1)
        self.assertEqual(c.tick(), 2)
        self.assertEqual(c.update(10), 11)       # max(2, 10) + 1
        self.assertEqual(c.update(3), 12)        # old stamp: still moves forward
        self.assertEqual(c.update(None), 13)     # unstamped message = local event

    def test_messages_carry_timestamps_and_preserve_causality(self):
        a, b = make_cluster([("tsA", 1), ("tsB", 2)])
        self.addCleanup(lambda: [n.stop() for n in (a, b)])
        for _ in range(3):
            a.clock.tick()                       # make A's clock run ahead of B's
        before = a.clock.time
        self.assertEqual(b.clock.time, 0)
        a.call(b.me, "election.ping", {})
        entries = [e for e in log_entries() if e.get("event") in ("SEND", "RECV")]
        # every message on the wire has an integer logical stamp
        for e in entries:
            self.assertIsInstance(e["message"]["lc"], int)
        req = next(e for e in entries if e["node"] == "tsA" and e["message"]["type"] == "election.ping")
        got = next(e for e in entries if e["node"] == "tsB" and e["event"] == "RECV"
                   and e["message"]["id"] == req["message"]["id"])
        rep = next(e for e in entries if e["node"] == "tsB" and e["event"] == "SEND"
                   and e["message"]["type"] == "election.ping.reply")
        back = next(e for e in entries if e["node"] == "tsA" and e["event"] == "RECV"
                    and e["message"]["id"] == rep["message"]["id"])
        # send -> receive -> reply -> receive: strictly increasing logical time
        self.assertGreater(req["lc"], before)
        self.assertGreater(got["lc"], req["lc"])
        self.assertGreater(rep["lc"], got["lc"])
        self.assertGreater(back["lc"], rep["lc"])
        self.assertGreater(b.clock.time, before)  # B jumped past A's clock


class TC2_BullyElection(unittest.TestCase):
    def setUp(self):
        self.nodes = make_cluster([(f"e{i}", i) for i in range(1, 6)])
        self.addCleanup(lambda: [n.stop() for n in self.nodes])

    def leaders(self, nodes):
        return {n.election.leader_name for n in nodes}

    def test_highest_id_wins(self):
        self.nodes[0].election.start_election()             # the weakest node starts it
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes) == {"e5"}))
        self.assertTrue(self.nodes[4].election.is_leader)

    def test_reelection_after_leader_crash(self):
        self.nodes[0].election.start_election()
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes) == {"e5"}))
        self.nodes[4].stop()                                 # the leader crashes
        alive = self.nodes[:4]
        alive[1].election.start_election()
        self.assertTrue(wait_for(lambda: self.leaders(alive) == {"e4"}))

    def test_new_higher_node_takes_over(self):
        self.nodes[0].election.start_election()
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes) == {"e5"}))
        newcomer = CoordinationNode("e9", 9).start()
        self.addCleanup(newcomer.stop)
        everyone = self.nodes + [newcomer]
        for n in everyone:
            n.set_peers([m.me for m in everyone])
        newcomer.election.start_election()
        self.assertTrue(wait_for(lambda: self.leaders(everyone) == {"e9"}))

    def test_heartbeat_monitor_detects_crashed_leader(self):
        self.nodes[0].election.start_election()
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes) == {"e5"}))
        for n in self.nodes[:4]:
            n.election.start_monitor(interval=0.2)
        self.nodes[4].stop()
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes[:4]) == {"e4"}, timeout=10))


class TC3_MutualExclusion(unittest.TestCase):
    N, ROUNDS = 4, 5

    def setUp(self):
        self.nodes = make_cluster([(f"m{i}", i) for i in range(self.N)])
        self.res = SharedResource(work_time=0.02).start()
        self.addCleanup(lambda: [x.stop() for x in [*self.nodes, self.res]])
        self.addr = ("127.0.0.1", self.res.port)

    def run_workers(self, nodes, protected):
        def work(node):
            for _ in range(self.ROUNDS):
                update_resource(node, self.addr, protected=protected)
        threads = [threading.Thread(target=work, args=(n,)) for n in nodes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)

    def test_unprotected_access_corrupts_the_resource(self):
        """Control experiment: without the algorithm the resource sees overlaps and loses updates."""
        self.run_workers(self.nodes, protected=False)
        st = self.res.state()
        self.assertTrue(st["violations"])
        self.assertLess(st["value"], self.N * self.ROUNDS)

    def test_ricart_agrawala_protects_the_resource(self):
        self.run_workers(self.nodes, protected=True)
        st = self.res.state()
        self.assertEqual(st["violations"], [])
        self.assertEqual(st["value"], self.N * self.ROUNDS)
        self.assertEqual([h["after"] for h in self.res.history], list(range(1, self.N * self.ROUNDS + 1)))
        self.assertTrue(all(n.mutex.entries == self.ROUNDS for n in self.nodes))

    def test_critical_sections_never_overlap_in_the_log(self):
        self.run_workers(self.nodes, protected=True)
        ev = [e for e in log_entries() if e.get("mutex", {}).get("action") in ("enter", "exit")
              and e["node"].startswith("m")]
        inside = set()
        for e in sorted(ev, key=lambda e: e["ts"]):
            who = e["mutex"]["node"]
            if e["mutex"]["action"] == "enter":
                self.assertFalse(inside, f"{who} entered while {inside} inside")
                inside.add(who)
            else:
                inside.discard(who)

    def test_older_request_goes_first(self):
        """Request order = (Lamport timestamp, name): m0 asks first and must enter first."""
        order = []
        a, b = self.nodes[0], self.nodes[1]
        a.mutex.acquire()                                    # a holds the CS
        t = threading.Thread(target=lambda: (b.mutex.acquire(), order.append("b"), b.mutex.release()))
        t.start()
        time.sleep(0.5)
        self.assertEqual(order, [])                          # b is blocked behind a
        order.append("a")
        a.mutex.release()
        t.join(10)
        self.assertEqual(order, ["a", "b"])

    def test_survives_a_crashed_node(self):
        self.nodes[3].stop()
        self.run_workers(self.nodes[:3], protected=True)
        st = self.res.state()
        self.assertEqual(st["violations"], [])
        self.assertEqual(st["value"], 3 * self.ROUNDS)


class TC4_SharedResource(unittest.TestCase):
    def test_state_over_rpc(self):
        res = SharedResource(work_time=0).start()
        self.addCleanup(res.stop)
        with RPCClient("t", "127.0.0.1", res.port) as c:
            self.assertEqual(c.call("resource.update", node="x", delta=5)["after"], 5)
            self.assertEqual(c.call("resource.state")["value"], 5)


if __name__ == "__main__":
    unittest.main()
