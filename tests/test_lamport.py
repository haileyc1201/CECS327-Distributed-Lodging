"""Tom's clock tests (UNG-100 / UNG-108 / UNG-109), on main's LamportClock and ``lc`` field.

Covers the extra guarantees folded into clock.py / msglog.py / transport.py:
thread safety, rejecting invalid stamps, one shared clock per node name, a fresh
stamp on every (re)send, local events ticking and causality through file signals.
"""
import json
import os
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src.communication.clock import LamportClock
from src.communication.codec import make_envelope, marshal
from src.communication.lookup import LookupNode
from src.communication.msglog import MessageLogger
from src.communication.signal_file import read_signal, write_signal
from src.communication.transport import HEADER, recv_message, send_message


class ClockTests(unittest.TestCase):
    def test_local_event_and_send(self):
        clock = LamportClock()
        self.assertEqual(clock.time, 0)
        self.assertEqual(clock.tick(), 1)
        self.assertEqual(clock.tick(), 2)

    def test_receive_lower_equal_and_higher(self):
        clock = LamportClock(10)
        self.assertEqual(clock.update(3), 11)
        self.assertEqual(clock.update(11), 12)
        self.assertEqual(clock.update(100), 101)

    def test_invalid_timestamps_do_not_advance_clock(self):
        clock = LamportClock()
        for value in (-1, 1.5, "3", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                clock.update(value)
        with self.assertRaises(ValueError):
            clock.update(None, strict=True)          # the transport's mode: unstamped frames are rejected
        self.assertEqual(clock.time, 0)
        with self.assertRaises(ValueError):
            LamportClock(-5)

    def test_unstamped_update_is_a_local_event_by_default(self):
        clock = LamportClock(4)                      # main's documented API is unchanged
        self.assertEqual(clock.update(None), 5)

    def test_concurrent_ticks_are_unique(self):
        clock = LamportClock()
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: clock.tick(), range(1000)))
        self.assertEqual(sorted(values), list(range(1, 1001)))

    def test_concurrent_updates_never_go_backwards(self):
        clock = LamportClock()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(clock.update, range(500)))
        self.assertGreaterEqual(clock.time, 500)


class TransportClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"COMM_LOG_FILE": str(self.directory / "messages.jsonl"),
                                          "COMM_NODE_LOG_DIR": str(self.directory / "nodes"), "COMM_QUIET": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def pair(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        return left, right

    def test_all_message_types_stamped_in_json_and_xml(self):
        kinds = ("rpc.request", "subscribe", "publish", "event", "topics", "group.join", "group.leave",
                 "group.members", "group.multicast", "group.deliver", "group.view", "ring.find_successor",
                 "ring.join_at", "ring.replicate", "ring.store", "ring.fetch", "ring.lookup",
                 "election.election", "election.coordinator", "election.ping", "mutex.request",
                 "resource.update", "control.ready")
        for fmt in ("json", "xml"):
            sender = MessageLogger(f"all-types-{fmt}-sender")
            receiver = MessageLogger(f"all-types-{fmt}-receiver")
            left, right = self.pair()
            receiver.clock.update(sender.clock.time + 100)
            for kind in kinds:
                for actual_kind in (kind, kind + ".reply"):
                    original = make_envelope(actual_kind, sender.node, {"ok": True})
                    before = receiver.clock.time
                    send_message(left, original, sender, receiver.node, fmt)
                    message, actual_format = recv_message(right, receiver, sender.node)
                    self.assertEqual(actual_format, fmt)
                    self.assertEqual(message["lc"], sender.clock.time)
                    self.assertEqual(receiver.clock.time, max(before, message["lc"]) + 1)
                    self.assertNotIn("lc", original, "send must not mutate a fan-out envelope")

    def test_shared_node_clock_and_threaded_per_node_log(self):
        first = MessageLogger("shared/node")
        second = MessageLogger("shared/node")
        self.assertIs(first.clock, second.clock)
        before = first.clock.time
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: (first if n % 2 else second).event("LOCAL", n=n), range(100)))
        events = [json.loads(line) for line in first.node_path.read_text().splitlines()]
        self.assertEqual([event["lc"] for event in events], list(range(before + 1, before + 101)))
        self.assertTrue(all(event["node"] == "shared/node" and event["event"] == "LOCAL" for event in events))
        self.assertEqual(first.node_path.parent, self.directory / "nodes")
        self.assertNotIn("/", first.node_path.name)

    def test_concurrent_sends_log_unique_stamps(self):
        sender, receiver = MessageLogger("busy-sender"), MessageLogger("busy-receiver")
        left, right = self.pair()

        def send(_):
            send_message(left, make_envelope("ping", sender.node, {}), sender, receiver.node)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(send, range(50)))
        stamps = [json.loads(line)["lc"] for line in sender.node_path.read_text().splitlines()]
        self.assertEqual(sorted(stamps), list(range(1, 51)))
        for _ in range(50):
            recv_message(right, receiver, sender.node)
        self.assertEqual(receiver.clock.time, 51)

    def test_forwarding_reused_envelope_gets_new_send_time(self):
        sender, receiver = MessageLogger("forwarder"), MessageLogger("forward-target")
        left, right = self.pair()
        envelope = make_envelope("ring.lookup", sender.node, {})
        stamps = []
        for _ in range(2):
            send_message(left, envelope, sender, receiver.node)
            message, _ = recv_message(right, receiver, sender.node)
            stamps.append(message["lc"])
        self.assertGreater(stamps[1], stamps[0])

    def test_local_ring_operations_also_tick(self):
        node = LookupNode("local-clock-peer")
        self.addCleanup(node.stop)
        before = node.clock.time
        node.put("local-key", "value")
        self.assertGreater(node.clock.time, before)
        before = node.clock.time
        self.assertEqual(node.lookup("local-key")["value"], "value")
        self.assertGreater(node.clock.time, before)
        kinds = {json.loads(line)["event"] for line in node.logger.node_path.read_text().splitlines()}
        self.assertTrue({"LOCAL_DISPATCH", "LOOKUP_START"} <= kinds)

    def test_info_entries_have_their_own_lc(self):
        log = MessageLogger("info-node")
        a = log.info("first")
        b = log.info("second")
        self.assertEqual(b, a + 1)
        self.assertEqual(log.info("given", stamp=99), 99)    # caller already ticked (mutex request)

    def test_file_control_signals_preserve_causality(self):
        child, driver = MessageLogger("signal-child"), MessageLogger("signal-driver")
        child.event("CS_ENTER")
        path = self.directory / "ready.json"
        write_signal(path, {"holder": child.node}, child, "control.entered")
        self.assertEqual(read_signal(path, driver), {"holder": child.node})
        driver.event("LEADER_KILL_REQUESTED")
        self.assertGreater(driver.clock.time, child.clock.time)
        release = self.directory / "release.json"
        write_signal(release, {}, driver, "control.release")
        read_signal(release, child)
        child.event("CS_EXIT")
        self.assertGreater(child.clock.time, driver.clock.time)

    def test_missing_or_invalid_wire_timestamp_rejected(self):
        receiver = MessageLogger("strict-receiver")
        for value in (None, -1, True, "12", 2.5):
            left, right = socket.socketpair()
            try:
                envelope = make_envelope("test", "untrusted", {})
                if value is not None:
                    envelope["lc"] = value
                body = marshal(envelope)
                left.sendall(HEADER.pack(len(body)) + b"J" + body)
                before = receiver.clock.time
                with self.assertRaises(ValueError):
                    recv_message(right, receiver, "untrusted")
                self.assertEqual(receiver.clock.time, before)
            finally:
                left.close()
                right.close()


if __name__ == "__main__":
    unittest.main()
