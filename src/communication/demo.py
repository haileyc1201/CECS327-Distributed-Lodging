"""End-to-end communication demo.

Starts every node as a separate OS process, then acts as the client:

  1. request-reply   availability.check over JSON-RPC (JSON and XML formats)
  2. request-reply   reservation.book  -> Reservation calls Property
  3. pub-sub         booking.created reaches 3 subscribers
  4. group comm      availability update multicast to 3 replicas; then one
                     replica is killed and the next multicast detects it and
                     shrinks the membership view

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
from .rpc import RPCClient
from .services import PORTS, REPLICA_GROUP

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
    try:
        banner("starting nodes (separate processes)")
        for role in ("property", "broker", "coordinator"):
            spawn(role, role)
        for p in ("property", "broker", "coordinator"):
            wait_port(PORTS[p])
        spawn("reservation", "reservation")
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
    print(f"\nFull log: {log_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
