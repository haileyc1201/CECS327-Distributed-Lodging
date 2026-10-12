"""Test cases for the communication milestone.

Run from the repository root:   python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import time
import unittest

os.environ["COMM_QUIET"] = "1"
_TMP = tempfile.mkdtemp()
os.environ["COMM_LOG_FILE"] = os.path.join(_TMP, "messages.jsonl")

from src.communication.broker import Broker, Publisher, Subscriber  # noqa: E402
from src.communication.codec import make_envelope, marshal, unmarshal  # noqa: E402
from src.communication.group import GroupCoordinator, GroupMember, coordinator_request, multicast  # noqa: E402
from src.communication.rpc import RPCClient, RPCError  # noqa: E402
from src.communication.services import PropertyNode, ReservationNode, replica_handler  # noqa: E402


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TC1_Marshalling(unittest.TestCase):
    def test_json_round_trip(self):
        env = make_envelope("rpc.request", "t", {"a": 1, "b": [True, None, 2.5, "x"], "c": {"d": "e"}})
        wire = marshal(env, "json")
        self.assertIsInstance(wire, bytes)
        self.assertEqual(unmarshal(wire, "json"), env)

    def test_xml_round_trip_preserves_types(self):
        env = make_envelope("event", "t", {"n": 3, "f": 1.5, "ok": False, "none": None, "l": [1, "2"]})
        wire = marshal(env, "xml")
        self.assertTrue(wire.startswith(b"<message>"))
        self.assertEqual(unmarshal(wire, "xml"), env)

    def test_envelope_has_iso_timestamp(self):
        env = make_envelope("x", "t", {})
        self.assertRegex(env["timestamp"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


class Cluster(unittest.TestCase):
    """Starts a full in-process cluster on ephemeral ports."""

    @classmethod
    def setUpClass(cls):
        cls.prop = PropertyNode(port=0).start()
        cls.broker = Broker(port=0).start()
        cls.coord = GroupCoordinator(port=0).start()
        cls.res = ReservationNode(port=0, property_addr=("127.0.0.1", cls.prop.port),
                                  broker_addr=("127.0.0.1", cls.broker.port),
                                  coordinator_addr=("127.0.0.1", cls.coord.port)).start()
        cls.subs = [Subscriber(n, "127.0.0.1", cls.broker.port, ["booking.created"]).start()
                    for n in ("notification-service", "analytics-service", "audit-service")]
        cls.replicas = []
        for i in range(3):
            m = GroupMember(f"replica-{i+1}", "property-replicas", "127.0.0.1", cls.coord.port,
                            on_message=replica_handler).start()
            m.join()
            cls.replicas.append(m)

    @classmethod
    def tearDownClass(cls):
        for s in cls.subs:
            s.close()
        for n in [cls.res, *cls.replicas, cls.coord, cls.broker, cls.prop]:
            n.stop()


class TC2_RequestReply(Cluster):
    def test_availability_check(self):
        with RPCClient("test", "127.0.0.1", self.prop.port) as c:
            self.assertTrue(c.call("availability.check", property_id=103)["available"])
            self.assertFalse(c.call("availability.check", property_id=102)["available"])

    def test_xml_rpc_call(self):
        with RPCClient("test", "127.0.0.1", self.prop.port, fmt="xml") as c:
            self.assertEqual(c.call("property.get", property_id=101)["name"], "Long Beach Apartment")

    def test_errors(self):
        with RPCClient("test", "127.0.0.1", self.prop.port) as c:
            with self.assertRaises(RPCError) as e:
                c.call("property.get", property_id=999)
            self.assertEqual(e.exception.code, 404)
            with self.assertRaises(RPCError) as e:
                c.call("no.such.method")
            self.assertEqual(e.exception.code, -32601)


class TC3_BookingPubSubGroup(Cluster):
    def test_booking_flow(self):
        with RPCClient("test", "127.0.0.1", self.res.port) as c:
            r = c.call("reservation.book", property_id=101, guest_name="Test", nights=2)
            self.assertEqual(r["status"], "accepted")
            self.assertEqual(r["reservation"]["amount"], 300)
            # pub-sub: all three subscribers got the event
            self.assertEqual(sorted(r["notified_subscribers"]),
                             ["analytics-service", "audit-service", "notification-service"])
            self.assertTrue(wait_for(lambda: all(len(s.received) == 1 for s in self.subs)))
            for s in self.subs:
                self.assertEqual(s.received[0]["event"]["reservation_id"], r["reservation"]["reservation_id"])
            # group communication: all three replicas applied the update
            self.assertEqual(sorted(r["replicas_updated"]), ["replica-1", "replica-2", "replica-3"])
            for m in self.replicas:
                self.assertEqual(m.state.get(101), False)
            # double booking rejected
            self.assertEqual(c.call("reservation.book", property_id=101)["status"], "rejected")


class TC4_GroupMembership(unittest.TestCase):
    def test_join_view_multicast_and_failure(self):
        coord = GroupCoordinator(port=0).start()
        members = [GroupMember(f"m{i}", "g", "127.0.0.1", coord.port).start() for i in range(3)]
        # always shut down and join every node (and the coordinator's view threads)
        for node in [*members, coord][::-1]:
            self.addCleanup(node.stop)
        for m in members:
            m.join()
        self.assertEqual(coordinator_request("t", "127.0.0.1", coord.port, "group.members", {"group": "g"})["members"],
                         ["m0", "m1", "m2"])
        self.assertTrue(wait_for(lambda: all(m.view == ["m0", "m1", "m2"] for m in members)))
        ack = multicast("t", "127.0.0.1", coord.port, "g", {"hello": 1})
        self.assertEqual(ack["delivered_to"], ["m0", "m1", "m2"])
        members[2].stop()
        time.sleep(0.6)
        ack = multicast("t", "127.0.0.1", coord.port, "g", {"hello": 2})
        self.assertEqual(ack["failed"], ["m2"])
        self.assertEqual(coord.members("g"), ["m0", "m1"])
        members[0].leave()
        self.assertEqual(coord.members("g"), ["m1"])


class TC5_Pubsub_Topics(unittest.TestCase):
    def test_only_matching_topic(self):
        b = Broker(port=0).start()
        self.addCleanup(b.stop)
        a = Subscriber("a", "127.0.0.1", b.port, ["t1"]).start()
        z = Subscriber("z", "127.0.0.1", b.port, ["t2"]).start()
        p = Publisher("p", "127.0.0.1", b.port)
        self.assertEqual(p.publish("t1", {"x": 1})["delivered_to"], ["a"])
        self.assertTrue(wait_for(lambda: len(a.received) == 1))
        self.assertEqual(z.received, [])
        for x in (a, z, p):
            x.close()


class TC6_Logging(unittest.TestCase):
    def test_every_entry_is_timestamped(self):
        with open(os.environ["COMM_LOG_FILE"], encoding="utf-8") as fh:
            entries = [json.loads(l) for l in fh]
        self.assertTrue(entries)
        for e in entries:
            self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        sends = [e for e in entries if e["event"] == "SEND"]
        self.assertTrue(all("message" in e and "wire" in e for e in sends))


if __name__ == "__main__":
    unittest.main()
