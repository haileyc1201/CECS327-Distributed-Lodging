"""Logical clocks, Bully election and Ricart-Agrawala mutual exclusion on a shared resource.

Run from the repository root:  python -m src.communication.coordination_demo
Every message (with its Lamport stamp ``lc``) is also in logs/messages.jsonl.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("COMM_QUIET", "1")  # messages still go to logs/messages.jsonl

from .node import make_cluster  # noqa: E402
from .resource import SharedResource, update_resource  # noqa: E402
from .rpc import RPCClient  # noqa: E402

UPDATES_PER_NODE = 3


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 60 - len(text)), flush=True)


def wait_for(cond, timeout=10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def hammer(nodes, addr, protected: bool) -> None:
    def work(node):
        for _ in range(UPDATES_PER_NODE):
            update_resource(node, addr, protected=protected)
    threads = [threading.Thread(target=work, args=(n,)) for n in nodes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def main() -> None:
    nodes = make_cluster([(f"node-{c}", i) for i, c in enumerate("ABCDE", 1)])
    resource = SharedResource(work_time=0.02).start()
    addr = ("127.0.0.1", resource.port)
    try:
        banner("1. logical clocks: every send ticks, every receive jumps past the stamp")
        a, b = nodes[0], nodes[1]
        for _ in range(5):
            a.clock.tick()                                   # node-A runs ahead with local events
        print(f"  before: node-A lc={a.clock.time}, node-B lc={b.clock.time}")
        a.call(b.me, "election.ping", {})
        print(f"  after A -> B ping and reply: node-A lc={a.clock.time}, node-B lc={b.clock.time}"
              f"  (B caught up past A's stamp)")

        banner("2. Bully election: the highest id wins")
        nodes[0].election.start_election()                   # the weakest node notices there is no leader
        wait_for(lambda: all(n.election.leader_name == "node-E" for n in nodes))
        print("  leaders as seen by each node:", {n.name: n.election.leader_name for n in nodes})

        print("\n  node-E (the leader) crashes; the others' heartbeat notices")
        for n in nodes[:4]:
            n.election.start_monitor(interval=0.2)
        nodes[4].stop()
        survivors = nodes[:4]
        wait_for(lambda: all(n.election.leader_name == "node-D" for n in survivors))
        print("  leaders as seen by the survivors:", {n.name: n.election.leader_name for n in survivors})

        banner("3. shared resource WITHOUT mutual exclusion")
        hammer(survivors, addr, protected=False)
        st = resource.state()
        print(f"  expected value {len(survivors) * UPDATES_PER_NODE}, got {st['value']}; "
              f"{len(st['violations'])} overlapping access(es) detected -> lost updates")

        resource.value, resource.history, resource.violations = 0, [], []
        banner("4. shared resource WITH Ricart-Agrawala mutual exclusion")
        hammer(survivors, addr, protected=True)
        st = resource.state()
        print(f"  expected value {len(survivors) * UPDATES_PER_NODE}, got {st['value']}; "
              f"{len(st['violations'])} overlapping access(es)")
        print("  order of access (node, resource lc):", [(h["node"], h["lc"]) for h in resource.history])
        print("  critical-section entries per node:", {n.name: n.mutex.entries for n in survivors})

        leader = next(n for n in survivors if n.election.is_leader)
        with RPCClient(leader.name, *addr, logger=leader.logger) as c:   # the leader verifies the result
            print(f"  leader {leader.name} reads the final state:", c.call("resource.state")["value"])
    finally:
        for n in [*nodes, resource]:
            n.stop()


if __name__ == "__main__":
    main()
