"""Bully leader election.

Every node has a rank (its ``id``); the live node with the highest rank must
become the leader (coordinator).

    ELECTION     a node that notices there is no (live) leader sends
                 election.election {id} to every node with a HIGHER id
    OK           a higher node answers election.election.reply {ok: true}
                 and starts an election of its own ("bullies" the sender)
    COORDINATOR  a node that gets no OK from anybody higher wins and sends
                 election.coordinator {leader} to everybody
    wait         a node that did get an OK waits for the COORDINATOR message of
                 the winner; if it does not come in time it starts over
    PING         election.ping is the heartbeat used by ``start_monitor``: a node
                 that cannot reach its leader starts an election

Crashed nodes simply never answer (connection refused / timeout), so the
election converges on the highest node that is still alive. A node that comes
back (or joins) with a higher id calls ``start_election`` and takes over.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import CoordinationNode

MAX_ROUNDS = 5


class BullyElection:
    def __init__(self, node: "CoordinationNode", ok_timeout: float = 1.0, coordinator_timeout: float = 3.0):
        self.node = node
        self.ok_timeout = ok_timeout                  # how long a higher node may take to say OK
        self.coordinator_timeout = coordinator_timeout  # how long to wait for the winner's announcement
        self.leader: dict | None = None
        self._lock = threading.Lock()
        self._electing = False
        self._announced = threading.Event()
        node.register("election.election", self._h_election)
        node.register("election.coordinator", self._h_coordinator)
        node.register("election.ping", self._h_ping)

    @property
    def leader_name(self) -> str | None:
        return self.leader["name"] if self.leader else None

    @property
    def is_leader(self) -> bool:
        return self.leader is not None and self.leader["name"] == self.node.name

    # ------------------------------------------------------------ the algorithm

    def start_election(self) -> dict | None:
        """Run an election from this node; returns the leader once one is known."""
        n = self.node
        with self._lock:
            if self._electing:                         # one election at a time per node
                return self.leader
            self._electing = True
        try:
            for _ in range(MAX_ROUNDS):
                self._announced.clear()
                higher = [p for p in n.peers if p["id"] > n.id]
                n.logger.info(f"ELECTION started by {n.name} (id {n.id}); asking higher nodes "
                              f"{[p['name'] for p in higher]}",
                              election={"action": "start", "by": n.name})
                answered = [p for p in higher
                            if n.try_call(p, "election.election", {"id": n.id, "name": n.name},
                                          timeout=self.ok_timeout) is not None]
                if not answered:                       # nobody stronger is alive: I win
                    self._declare_victory()
                    return self.leader
                n.logger.info(f"OK from {[p['name'] for p in answered]}; waiting for their COORDINATOR",
                              election={"action": "wait", "by": n.name})
                if self._announced.wait(self.coordinator_timeout):
                    return self.leader
                n.logger.info("no COORDINATOR announced in time; restarting the election",
                              election={"action": "retry", "by": n.name})
            return self.leader
        finally:
            with self._lock:
                self._electing = False

    def _declare_victory(self) -> None:
        n = self.node
        with self._lock:
            self.leader = n.me
        for p in n.peers:
            n.try_call(p, "election.coordinator", {"leader": n.me}, timeout=self.ok_timeout)
        n.logger.info(f"COORDINATOR: {n.name} (id {n.id}) is the leader",
                      election={"action": "won", "leader": n.name})

    # ------------------------------------------------------------ handlers

    def _h_election(self, body: dict) -> dict:
        """A lower node asks for an election: answer OK and run my own."""
        if int(body["id"]) < self.node.id:
            threading.Thread(target=self.start_election, daemon=True).start()
            return {"ok": True, "id": self.node.id}
        return {"ok": False, "id": self.node.id}

    def _h_coordinator(self, body: dict) -> dict:
        leader = body["leader"]
        if leader["id"] < self.node.id:                # a weaker node claims leadership: not acceptable
            threading.Thread(target=self.start_election, daemon=True).start()
            return {"ack": False}
        with self._lock:
            self.leader = leader
        self._announced.set()
        self.node.logger.info(f"{self.node.name} accepts {leader['name']} (id {leader['id']}) as leader",
                              election={"action": "accept", "leader": leader["name"]})
        return {"ack": True}

    def _h_ping(self, body: dict) -> dict:
        return {"alive": self.node.name, "leader": self.leader_name}

    # ------------------------------------------------------------ failure detection

    def start_monitor(self, interval: float = 0.5) -> threading.Thread:
        """Background heartbeat: no leader, or leader unreachable -> start an election."""
        n = self.node

        def loop():
            while not n._stop.is_set():
                time.sleep(interval)
                leader = self.leader
                if leader is not None and leader["name"] == n.name:
                    continue
                if leader is not None and n.try_call(leader, "election.ping", {}, timeout=interval) is not None:
                    continue
                n.logger.info(f"leader {leader['name'] if leader else None} unreachable; starting an election",
                              election={"action": "leader-lost", "by": n.name})
                with self._lock:
                    self.leader = None
                self.start_election()

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t
