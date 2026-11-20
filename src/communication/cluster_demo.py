"""Reservation cluster demo: Bully election + Ricart-Agrawala mutual exclusion + logical clocks,
wired into the booking flow (Property node, broker, group coordinator, three reservation nodes).

Run from the repository root:  python -m src.communication.cluster_demo
Every message with its Lamport stamp ``lc`` is in logs/messages.jsonl.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("COMM_QUIET", "1")  # messages still go to logs/messages.jsonl

from .broker import Broker, Subscriber  # noqa: E402
from .group import GroupCoordinator  # noqa: E402
from .rpc import RPCClient  # noqa: E402
from .services import LEADER_TOPIC, BOOKING_TOPIC, PropertyNode, ReservationNode  # noqa: E402


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 60 - len(text)), flush=True)


def wait_for(cond, timeout=10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def book_at_once(nodes, property_id: int) -> list[dict]:
    """Every node receives a booking for the same property at the same moment."""
    replies, barrier = [], threading.Barrier(len(nodes))

    def work(node):
        with RPCClient("guest", "127.0.0.1", node.port, timeout=30) as c:
            barrier.wait()
            r = c.call("reservation.book", property_id=property_id, guest_name=f"guest@{node.name}")
            replies.append((node.name, r["status"]))

    threads = [threading.Thread(target=work, args=(n,)) for n in nodes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(replies)


def main() -> None:
    prop = PropertyNode(port=0).start()
    broker = Broker(port=0).start()
    group = GroupCoordinator(port=0).start()
    watcher = Subscriber("cluster-watcher", "127.0.0.1", broker.port, [LEADER_TOPIC, BOOKING_TOPIC]).start()
    nodes = [ReservationNode(port=0, property_addr=("127.0.0.1", prop.port), broker_addr=("127.0.0.1", broker.port),
                             coordinator_addr=("127.0.0.1", group.port), name=f"reservation-{c}", node_id=i,
                             election_monitor=None, book_delay=0.1).start()
             for i, c in enumerate("ABC", 1)]
    try:
        peers = [n.coord.me for n in nodes]
        for n in nodes:
            n.join_cluster(peers)
        reset = lambda pid: RPCClient("admin", "127.0.0.1", prop.port).call(   # noqa: E731
            "property.set_available", property_id=pid, available=True)

        banner("1. the cluster elects a leader (Bully: highest rank wins)")
        for n in nodes:
            n.coord.election.start_monitor(0.2)            # no leader known -> start an election
        wait_for(lambda: {n.coord.election.leader_name for n in nodes} == {"reservation-C"})
        for n in nodes:
            with RPCClient("guest", "127.0.0.1", n.port) as c:
                print("  ", c.call("reservation.status"))
        wait_for(lambda: any(e["topic"] == LEADER_TOPIC for e in watcher.received))
        print("   announced on the broker:", [e["event"] for e in watcher.received if e["topic"] == LEADER_TOPIC])

        banner("2. three nodes sell property 101 at the same moment: WITHOUT the mutex")
        for n in nodes:
            n.use_mutex = False
        replies = book_at_once(nodes, 101)
        print("  ", replies, "-> sold", sum(s == "accepted" for _, s in replies), "times: double booking!")

        banner("3. same race WITH Ricart-Agrawala mutual exclusion across the cluster")
        reset(101)
        for n in nodes:
            n.use_mutex = True
        replies = book_at_once(nodes, 101)
        print("  ", replies, "-> sold", sum(s == "accepted" for _, s in replies), "time")
        print("   critical-section entries per node:", {n.name: n.coord.mutex.entries for n in nodes})

        banner("4. the leader crashes; the survivors elect a new one and keep selling")
        nodes[2].stop()
        wait_for(lambda: {n.coord.election.leader_name for n in nodes[:2]} == {"reservation-B"})
        print("   leader now:", {n.name: n.coord.election.leader_name for n in nodes[:2]})
        print("  ", book_at_once(nodes[:2], 103), "(property 103, two nodes at once)")

        banner("5. one logical clock per node")
        for n in nodes[:2]:
            print(f"   {n.name}: lc={n.logger.clock.time}  (RPC server, election, mutex, property calls, "
                  f"pub-sub and multicast all tick it)")
    finally:
        watcher.close()
        for n in [*nodes, group, broker, prop]:
            n.stop()


if __name__ == "__main__":
    main()
