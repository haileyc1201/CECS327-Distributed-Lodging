"""End-to-end communication demo.

Starts every node as a separate OS process, then acts as the client:

  0. ring overlay    4 ring peers join; the Property and Reservation nodes keep their
                     data in the ring
  1. request-reply   availability.check over JSON-RPC (JSON and XML formats)
  2. request-reply   reservation.book  -> Reservation calls Property
  3. pub-sub         booking.created reaches 3 subscribers
  4. group comm      availability update multicast to 3 replicas; then one
                     replica is killed and the next multicast detects it and
                     shrinks the membership view
  5. peer join/leave one ring peer leaves gracefully (hands its data to its
                     neighbour), another is killed (heartbeat detects it, the
                     neighbours are repaired); the property data survives both
  6. persistence     the Reservation node is restarted and still finds its reservations

Run from the repository root:  python -m src.communication.demo
Logs: logs/messages.jsonl (one ISO-8601 timestamped JSON line per send/receive)
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .codec import make_envelope, marshal, unmarshal
from .group import coordinator_request, multicast
from .msglog import MessageLogger, log_path
from .ring import RingClient
from .rpc import RPCClient
from .services import PORTS, REPLICA_GROUP, RING_PORTS

ROOT = Path(__file__).resolve().parents[2]


def wait_port(port: int, timeout: float = 10) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {port} never opened")


def wait_joined(rc: RingClient, port: int, timeout: float = 10) -> None:
    """Wait until the ring peer on `port` has found its neighbours (finished joining)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = rc.call(("127.0.0.1", port), "ring.state", {})
            if s["succs"] != [s["name"]]:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"ring peer on port {port} never joined")


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 60 - len(text)), flush=True)


def main() -> int:
    if "--keep-log" not in sys.argv and log_path().exists():
        log_path().unlink()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    procs: dict[str, subprocess.Popen] = {}

    def spawn(name, *args):
        out = open(ROOT / "logs" / f"{name}.out", "w")
        procs[name] = subprocess.Popen([sys.executable, "-m", "src.communication.run", *args],
                                       cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)

    (ROOT / "logs").mkdir(exist_ok=True)
    ring_ports = list(RING_PORTS.values())
    ring_arg = ",".join(map(str, ring_ports))
    rc = RingClient("client", [("127.0.0.1", p) for p in ring_ports])
    try:
        banner("starting nodes (separate processes)")
        for i, (name, port) in enumerate(RING_PORTS.items()):      # ring peers first: peer-to-peer join
            spawn(name, "ring", name, str(port), *([str(ring_ports[0])] if i else []))
            wait_port(port)
            if i:
                wait_joined(rc, port)                               # one join at a time
        spawn("property", "property", "--ring", ring_arg)
        for role in ("broker", "coordinator"):
            spawn(role, role)
        for p in ("property", "broker", "coordinator"):
            wait_port(PORTS[p])
        spawn("reservation", "reservation", "--ring", ring_arg)
        wait_port(PORTS["reservation"])
        for name in ("notification-service", "analytics-service", "audit-service"):
            spawn(name, "subscriber", name)
        for i in (1, 2, 3):
            spawn(f"replica-{i}", "replica", f"replica-{i}", str(6100 + i))
        time.sleep(1.5)
        for name, p in procs.items():
            print(f"  {name:<22} pid={p.pid}")

        client_log = MessageLogger("client")
        banner("marshalling: envelope -> JSON bytes / XML bytes -> envelope")
        env_obj = make_envelope("rpc.request", "client",
                                {"jsonrpc": "2.0", "method": "availability.check", "params": {"property_id": 101}, "id": 0})
        for fmt in ("json", "xml"):
            wire = marshal(env_obj, fmt)
            back = unmarshal(wire, fmt)
            print(f"  {fmt}: {len(wire)} bytes, round-trip equal = {back == env_obj}")
            print("   ", wire.decode()[:160] + ("..." if len(wire) > 160 else ""))
            client_log.info(f"marshal round-trip {fmt}", before=env_obj, after=wire.decode(), equal=back == env_obj)

        banner("1. request-reply: availability.check (JSON-RPC over TCP)")
        with RPCClient("client", "127.0.0.1", PORTS["property"]) as prop:
            print("  101 ->", prop.call("availability.check", property_id=101))
            print("  102 ->", prop.call("availability.check", property_id=102))
        with RPCClient("client", "127.0.0.1", PORTS["property"], fmt="xml") as prop_xml:
            print("  103 (XML on the wire) ->", prop_xml.call("availability.check", property_id=103))

        print("\n  group members:", coordinator_request("client", "127.0.0.1", PORTS["coordinator"],
                                                         "group.members", {"group": REPLICA_GROUP})["members"])

        banner("2+3+4. reservation.book -> property RPC, pub-sub, multicast")
        with RPCClient("client", "127.0.0.1", PORTS["reservation"]) as res:
            ok = res.call("reservation.book", property_id=101, guest_name="Demo Guest", nights=2)
            print("  booking 101:", json.dumps(ok, indent=2))
            booked_id = ok["reservation"]["reservation_id"]
            again = res.call("reservation.book", property_id=101, guest_name="Second Guest")
            print("  booking 101 again:", again)
            busy = res.call("reservation.book", property_id=102, guest_name="Demo Guest")
            print("  booking 102:", busy)

        banner("4b. failure: kill replica-3, multicast again")
        procs["replica-3"].terminate()
        procs["replica-3"].wait(5)
        time.sleep(0.3)
        ack = multicast("client", "127.0.0.1", PORTS["coordinator"], REPLICA_GROUP,
                        {"op": "availability_update", "property_id": 103, "available": True})
        print("  multicast ack:", ack)
        print("  group members now:", coordinator_request("client", "127.0.0.1", PORTS["coordinator"],
                                                            "group.members", {"group": REPLICA_GROUP})["members"])
        time.sleep(0.5)

        banner("5. ring overlay: peer leave (graceful) and crash (heartbeat)")

        def show_ring(ports):
            for port in sorted(ports, key=lambda p: rc.call(("127.0.0.1", p), "ring.state", {})["id"]):
                s = rc.call(("127.0.0.1", port), "ring.state", {})
                print(f"  {s['name']:<7} id={s['id']:>5}  pred={s['pred']:<7} succs={s['succs']}  "
                      f"keys={len(s['keys'])} replicas={len(s['replicas'])}")

        def check_data(label):
            with RPCClient("client", "127.0.0.1", PORTS["property"]) as prop:
                props = prop.call("property.list")
                print(f"  [{label}] {len(props)} properties readable; "
                      f"101 available = {prop.call('availability.check', property_id=101)['available']} (booked above)")
            with RPCClient("client", "127.0.0.1", PORTS["reservation"]) as res:
                print(f"  [{label}] reservation {booked_id} readable = "
                      f"{res.call('reservation.get', reservation_id=booked_id)['status']}; "
                      f"{len(res.call('reservation.list'))} reservation(s) listed")

        live = list(ring_ports)
        print("  ring, ordered by position:")
        show_ring(live)
        check_data("before")

        leaver = "ring-B"
        print(f"\n  {leaver} leaves gracefully (hands its keys to its successor)")
        rc.call(("127.0.0.1", RING_PORTS[leaver]), "ring.leave", {})
        live.remove(RING_PORTS[leaver])
        time.sleep(1.5)
        show_ring(live)
        check_data(f"after {leaver} left")

        victim = "ring-C"
        print(f"\n  {victim} crashes (process killed, no goodbye)")
        procs[victim].terminate()
        procs[victim].wait(5)
        live.remove(RING_PORTS[victim])
        time.sleep(3.5)                                             # heartbeat detects + repairs
        show_ring(live)
        check_data(f"after {victim} crashed")

        banner("6. reservation node restarts; its reservations are still in the ring")
        procs["reservation"].terminate()
        procs["reservation"].wait(5)
        spawn("reservation", "reservation", "--ring", ring_arg)
        wait_port(PORTS["reservation"])
        with RPCClient("client", "127.0.0.1", PORTS["reservation"]) as res:
            print("  reservation.get  ->", res.call("reservation.get", reservation_id=booked_id))
            print("  reservation.list ->", len(res.call("reservation.list")), "reservation(s)")
    finally:
        for p in procs.values():
            p.terminate()
        for p in procs.values():
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    banner("summary from logs/messages.jsonl")
    entries = [json.loads(l) for l in open(log_path(), encoding="utf-8")]
    sends = sum(e["event"] == "SEND" for e in entries)
    recvs = sum(e["event"] == "RECV" for e in entries)
    print(f"  {len(entries)} log entries, {sends} SEND, {recvs} RECV")
    for node in ("notification-service", "analytics-service", "audit-service", "replica-1", "replica-2"):
        notes = [e["note"] for e in entries if e["node"] == node and e["event"] == "INFO" and "listening" not in e["note"]]
        print(f"  {node:<22} {notes}")
    ring_notes = [(e["node"], e["note"]) for e in entries
                  if e["node"].startswith("ring-") and e["event"] == "INFO" and "listening" not in e["note"]]
    print("  ring events:")
    for node, note in ring_notes:
        print(f"    {node:<7} {note}")
    print(f"\nFull log: {log_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())