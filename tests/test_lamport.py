"""Lamport rules and clock coverage at the shared transport boundary."""
import json
import os
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src.communication.codec import make_envelope, marshal
from src.communication.lamport import LamportClock
from src.communication.msglog import MessageLogger
from src.communication.signal_file import read_signal, write_signal
from src.communication.lookup import LookupNode
from src.communication.transport import HEADER, recv_message, send_message


class ClockTests(unittest.TestCase):
    def test_local_event_and_send(self):
        clock = LamportClock()
        self.assertEqual(clock.value, 0)
        self.assertEqual(clock.tick(), 1)
        self.assertEqual(clock.send(), 2)

    def test_receive_lower_equal_and_higher(self):
        clock = LamportClock(10)
        self.assertEqual(clock.receive(3), 11)
        self.assertEqual(clock.receive(11), 12)
        self.assertEqual(clock.receive(100), 101)

    def test_invalid_timestamps_do_not_advance_clock(self):
        clock = LamportClock()
        for value in (-1, 1.5, "3", None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                clock.receive(value)
        self.assertEqual(clock.value, 0)

    def test_concurrent_ticks_are_unique(self):
        clock = LamportClock()
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: clock.tick(), range(1000)))
        self.assertEqual(sorted(values), list(range(1, 1001)))


class TransportClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"COMM_LOG_FILE": str(self.directory / "messages.jsonl"),
                                          "COMM_NODE_LOG_DIR": str(self.directory / "nodes"), "COMM_QUIET": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_all_message_types_stamped_in_json_and_xml(self):
        # The future election/lock messages have no separate stamping path.
        kinds = ("rpc.request", "rpc.reply", "subscribe", "subscribe.ack", "publish", "publish.ack", "event",
                 "topics", "topics.reply", "group.join", "group.join.ack", "group.leave", "group.leave.ack",
                 "group.members", "group.members.reply", "group.multicast", "group.multicast.ack",
                 "group.deliver", "group.ack", "group.view", "ring.find_successor", "ring.join_at",
                 "ring.set_successor", "ring.set_predecessor", "ring.take_data", "ring.replicate", "ring.ping",
                 "ring.store", "ring.fetch", "ring.state", "ring.leave", "ring.lookup",
                 "ELECTION", "COORDINATOR", "REPLICATE", "REQUEST", "GRANT", "RELEASE")
        for fmt in ("json", "xml"):
            sender = MessageLogger(f"all-types-{fmt}-sender")
            receiver = MessageLogger(f"all-types-{fmt}-receiver")
            left, right = socket.socketpair()
            self.addCleanup(left.close)
            self.addCleanup(right.close)
            receiver.clock.receive(sender.clock.value + 100)
            for kind in kinds:
                for actual_kind in (kind, kind + ".reply"):
                    original = make_envelope(actual_kind, sender.node, {"ok": True})
                    before = receiver.clock.value
                    send_message(left, original, sender, receiver.node, fmt)
                    message, actual_format = recv_message(right, receiver, sender.node)
                    self.assertEqual(actual_format, fmt)
                    self.assertEqual(message["logical_timestamp"], sender.clock.value)
                    self.assertEqual(receiver.clock.value, max(before, message["logical_timestamp"]) + 1)
                    self.assertEqual(original["logical_timestamp"], 0, "send must not mutate a fanout envelope")
            left.close()
            right.close()

    def test_shared_node_clock_and_threaded_per_node_log(self):
        first = MessageLogger("shared/node")
        second = MessageLogger("shared/node")
        self.assertIs(first.clock, second.clock)
        before = first.clock.value
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: (first if n % 2 else second).event("LOCAL", {"n": n}), range(100)))
        events = [json.loads(line) for line in first.node_path.read_text().splitlines()]
        self.assertEqual([event["timestamp"] for event in events], list(range(before + 1, before + 101)))
        self.assertTrue(all(event["node_id"] == "shared/node" and event["event"] == "LOCAL" for event in events))
        self.assertEqual(first.node_path.parent, self.directory / "nodes")
        self.assertNotIn("/", first.node_path.name)

    def test_forwarding_reused_envelope_gets_new_send_time(self):
        sender, receiver = MessageLogger("forwarder"), MessageLogger("forward-target")
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        envelope = make_envelope("ring.lookup", sender.node, {})
        timestamps = []
        for _ in range(2):
            send_message(left, envelope, sender, receiver.node)
            message, _ = recv_message(right, receiver, sender.node)
            timestamps.append(message["logical_timestamp"])
        self.assertGreater(timestamps[1], timestamps[0])

    def test_local_ring_operations_also_tick(self):
        node = LookupNode("local-clock-peer")
        self.addCleanup(node.stop)
        before = node.clock.value
        node.put("local-key", "value")
        self.assertGreater(node.clock.value, before)
        before = node.clock.value
        self.assertEqual(node.lookup("local-key")["value"], "value")
        self.assertGreater(node.clock.value, before)
        kinds = {json.loads(line)["event"] for line in node.logger.node_path.read_text().splitlines()}
        self.assertTrue({"LOCAL_DISPATCH", "LOOKUP_START"} <= kinds)

    def test_file_control_signals_preserve_causality(self):
        child, driver = MessageLogger("signal-child"), MessageLogger("signal-driver")
        child.event("CS_ENTER")
        path = self.directory / "ready.json"
        write_signal(path, {"holder": child.node}, child, "control.entered")
        self.assertEqual(read_signal(path, driver), {"holder": child.node})
        driver.event("LEADER_KILL_REQUESTED")
        self.assertGreater(driver.clock.value, child.clock.value)
        release = self.directory / "release.json"
        write_signal(release, {}, driver, "control.release")
        read_signal(release, child)
        child.event("CS_EXIT")
        self.assertGreater(child.clock.value, driver.clock.value)

    def test_missing_or_invalid_wire_timestamp_rejected(self):
        receiver = MessageLogger("strict-receiver")
        for value in (None, -1, True, "12"):
            left, right = socket.socketpair()
            try:
                envelope = make_envelope("test", "untrusted", {})
                envelope["logical_timestamp"] = value
                body = marshal(envelope)
                left.sendall(HEADER.pack(len(body)) + b"J" + body)
                before = receiver.clock.value
                with self.assertRaises(ValueError):
                    recv_message(right, receiver, "untrusted")
                self.assertEqual(receiver.clock.value, before)
            finally:
                left.close()
                right.close()
