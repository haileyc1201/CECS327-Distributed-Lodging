"""Integration tests: reservation cluster = Bully election + Ricart-Agrawala + one logical clock per node.

Run from the repository root:   python -m unittest tests.test_cluster -v
"""
import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

os.environ["COMM_QUIET"] = "1"
_TMP = tempfile.mkdtemp()
os.environ["COMM_LOG_FILE"] = os.path.join(_TMP, "messages.jsonl")

from src.communication import services  # noqa: E402
from src.communication.broker import Broker, Subscriber  # noqa: E402
from src.communication.group import GroupCoordinator  # noqa: E402
from src.communication.ring import RingClient, RingNode  # noqa: E402
from src.communication.rpc import RPCClient  # noqa: E402
from src.communication.services import PropertyNode, ReservationNode  # noqa: E402


def wait_for(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class ClusterBase(unittest.TestCase):
    use_mutex = True
    book_delay = 0.1
    ring = False

    def setUp(self):
        self.tag = uuid.uuid4().hex[:4]                      # unique node names -> unique entries in the shared log
        self.to_stop = []
        self.cleanups = []
        if self.ring:
            self.setUpRing()
        self.prop = self.track(PropertyNode(port=0, ring=self.ring_client("property")))
        self.broker = self.track(Broker(port=0))
        self.group = self.track(GroupCoordinator(port=0))
        self.nodes = []
        for i, letter in enumerate("ABC", 1):
            n = ReservationNode(port=0, property_addr=("127.0.0.1", self.prop.port),
                                broker_addr=("127.0.0.1", self.broker.port),
                                coordinator_addr=("127.0.0.1", self.group.port),
                                name=f"{self.tag}-res-{letter}", node_id=i, election_monitor=None,
                                use_mutex=self.use_mutex, book_delay=self.book_delay,
                                ring=self.ring_client(f"res-{letter}"))
            self.nodes.append(self.track(n))
        peers = [n.coord.me for n in self.nodes]
        for n in self.nodes:
            n.join_cluster(peers)
        self.addCleanup(self.stop_all)

    def setUpRing(self):
        self.ring_nodes = [RingNode(f"{self.tag}-ring-{c}", port=0).start() for c in "ABCD"]
        self.to_stop += self.ring_nodes
        for n in self.ring_nodes[1:]:
            n.join(self.ring_nodes[0].host, self.ring_nodes[0].port)
        for _ in range(2):
            for n in self.ring_nodes:
                n.stabilize()

    def ring_client(self, who):
        if not self.ring:
            return None
        return RingClient(f"{self.tag}-{who}", [("127.0.0.1", self.ring_nodes[0].port)])

    def track(self, node):
        node.start()
        self.to_stop.append(node)
        return node

    def stop_all(self):
        for n in reversed(self.to_stop):
            n.stop()

    def leaders(self, nodes):
        return {n.coord.election.leader_name for n in nodes}

    def book_concurrently(self, nodes, property_ids):
        """One thread per (node, property) booking at the same moment; returns every reply."""
        replies, barrier = [], threading.Barrier(len(nodes))

        def work(node, pid):
            with RPCClient("guest", "127.0.0.1", node.port, timeout=30) as c:
                barrier.wait()
                replies.append(c.call("reservation.book", property_id=pid, guest_name=f"g{pid}"))

        threads = [threading.Thread(target=work, args=(n, pid)) for n, pid in zip(nodes, property_ids)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        return replies


class TC1_ElectionInTheCluster(ClusterBase):
    def test_leader_is_elected_reported_and_announced(self):
        sub = Subscriber("watcher", "127.0.0.1", self.broker.port, [services.LEADER_TOPIC]).start()
        self.addCleanup(sub.close)
        self.nodes[0].coord.election.start_election()
        top = self.nodes[2].name
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes) == {top}))
        for n in self.nodes:                                 # clients can ask any node who the primary is
            with RPCClient("guest", "127.0.0.1", n.port) as c:
                st = c.call("reservation.status")
            self.assertEqual(st["leader"], top)
            self.assertEqual(st["is_leader"], n is self.nodes[2])
        # the winner announced itself over pub-sub
        self.assertTrue(wait_for(lambda: len(sub.received) >= 1))
        self.assertEqual(sub.received[0]["event"]["leader"], top)

    def test_failover_then_bookings_still_exclusive(self):
        self.nodes[0].coord.election.start_election()
        self.assertTrue(wait_for(lambda: self.leaders(self.nodes) == {self.nodes[2].name}))
        survivors = self.nodes[:2]
        for n in survivors:
            n.coord.election.start_monitor(interval=0.2)
        self.nodes[2].stop()                                 # the leader crashes
        self.assertTrue(wait_for(lambda: self.leaders(survivors) == {self.nodes[1].name}))
        replies = self.book_concurrently(survivors, [103, 103])
        self.assertEqual(sorted(r["status"] for r in replies), ["accepted", "rejected"])


class TC2_MutualExclusionOnBookings(ClusterBase):
    def test_same_property_is_sold_only_once(self):
        replies = self.book_concurrently(self.nodes, [101, 101, 101])
        self.assertEqual(sorted(r["status"] for r in replies), ["accepted", "rejected", "rejected"])
        with RPCClient("guest", "127.0.0.1", self.prop.port) as c:
            self.assertFalse(c.call("availability.check", property_id=101)["available"])

    def test_critical_sections_do_not_overlap(self):
        self.book_concurrently(self.nodes, [101, 101, 103])
        with open(os.environ["COMM_LOG_FILE"], encoding="utf-8") as fh:
            ev = [e for e in map(json.loads, fh) if e.get("mutex", {}).get("action") in ("enter", "exit")
                  and e["node"].startswith(self.tag)]
        inside = set()
        for e in ev:
            if e["mutex"]["action"] == "enter":
                self.assertFalse(inside)
                inside.add(e["node"])
            else:
                inside.discard(e["node"])
        self.assertEqual(sum(e["mutex"]["action"] == "enter" for e in ev), 3)


class TC3_WithoutTheMutex(ClusterBase):
    use_mutex = False

    def test_control_experiment_double_booking(self):
        """Same race, mutex switched off: several nodes sell property 101."""
        replies = self.book_concurrently(self.nodes, [101, 101, 101])
        self.assertGreater(sum(r["status"] == "accepted" for r in replies), 1)


class TC4_OneClockPerNode(ClusterBase):
    def test_every_component_uses_the_nodes_clock(self):
        self.book_concurrently(self.nodes, [101, 103, 101])
        for n in self.nodes:
            self.assertIs(n.coord.logger, n.logger)
            self.assertIs(n.coord.clock, n.logger.clock)
            self.assertIs(n._prop().logger, n.logger)
            self.assertIs(n._pub().logger, n.logger)
        # one clock => every message a node sends (RPC replies, mutex, property calls, pub-sub,
        # multicast) has a different logical stamp
        with open(os.environ["COMM_LOG_FILE"], encoding="utf-8") as fh:
            sends = [e for e in map(json.loads, fh) if e["event"] == "SEND" and e["node"].startswith(self.tag)]
        for n in self.nodes:
            stamps = [e["lc"] for e in sends if e["node"] == n.name]
            self.assertTrue(stamps)
            self.assertEqual(len(stamps), len(set(stamps)), f"{n.name} reused a logical time")


class TC5_RingBackedCluster(ClusterBase):
    ring = True
    book_delay = 0.0

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump([{"id": 200 + i, "name": f"Room {i}", "price": 100 + i, "available": True} for i in range(8)],
                  self.tmp)
        self.tmp.close()
        patcher = mock.patch.object(services, "DATA_FILE", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_reservation_index_keeps_every_booking(self):
        """Three nodes share the reservation index in the ring (read-modify-write); none may be lost."""
        ids = list(range(200, 208))
        nodes = [self.nodes[i % 3] for i in range(8)]
        replies = self.book_concurrently(nodes, ids)
        self.assertEqual([r["status"] for r in replies], ["accepted"] * 8)
        for n in self.nodes:
            with RPCClient("guest", "127.0.0.1", n.port) as c:
                self.assertEqual(len(c.call("reservation.list")), 8)


if __name__ == "__main__":
    unittest.main()
