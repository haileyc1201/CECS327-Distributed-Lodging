"""TEMPORARY stand-in for Josiah's UNG-102 / UNG-103, not their implementation.

Known, fixed local membership; Bully-style highest-live-priority election and a
central REQUEST / GRANT / RELEASE lock. Replicate holder state before replying
GRANT, then RESTORE it after a coordinator crash. A live old holder must release
before another client can enter. Retries with the same request id are idempotent.

Failure model: one fail-stop coordinator crash, surviving clients, reliable
local TCP. No partitions, simultaneous client/coordinator loss, Byzantine peers,
or restart/rejoin. This small coursework stand-in is NOT a production consensus
protocol and must be replaced by the team's coordinator behind RecoveryAdapter.
"""
from __future__ import annotations

import argparse
import threading
from pathlib import Path

from src.communication.codec import make_envelope
from src.communication.msglog import MessageLogger
from src.communication.server import FramedServer
from src.communication.signal_file import write_signal
from src.communication.transport import ConnectionClosed, connect, recv_message, send_message

NET_ERRORS = (OSError, ValueError, ConnectionClosed)


def request(peer: dict, kind: str, payload: dict, logger: MessageLogger) -> dict:
    label = f"{peer['host']}:{peer['port']}"
    with connect(peer["host"], peer["port"], timeout=0.8) as connection:
        send_message(connection, make_envelope(kind, logger.node, payload, receiver=peer["name"]), logger, label)
        reply, _ = recv_message(connection, logger, label)
    return reply["payload"]


class StandinCoordinator(FramedServer):
    def __init__(self, name: str, priority: int):
        super().__init__(name)
        self.priority = priority
        self.peers: dict[str, dict] = {}
        self.leader_id: str | None = None
        self.lock_state = {"holder": None, "request_id": None, "token": None,
                           "version": 0, "last_released": None}
        self._state_lock = threading.RLock()
        self._monitor: threading.Thread | None = None

    def _install_leader(self, leader: str) -> None:
        with self._state_lock:
            previous = self.leader_id
            if previous == leader:
                return
            self.leader_id = leader
            self.logger.event("LEADER_ELECTED", {"leader": leader, "previous": previous,
                                                 "algorithm": "stand-in Bully/highest-live-priority"})
            if leader == self.name:
                # NEVER clear the old holder just because the coordinator died.
                # Its grant was replicated before GRANT, so preserve it until
                # a matching RELEASE. No second grant can overlap that holder.
                self.logger.event("LOCK_STATE_RESTORED", {"policy": "restore", **self.lock_state})

    def _elect(self) -> None:
        while not self._stop.is_set():
            higher = []
            for peer in sorted(self.peers.values(), key=lambda item: item["priority"], reverse=True):
                if peer["priority"] <= self.priority:
                    continue
                try:
                    reply = request(peer, "ELECTION", {}, self.logger)
                    if reply.get("status") == "OK":
                        higher.append(peer)
                except NET_ERRORS:
                    pass
            leader = higher[0]["name"] if higher else self.name
            previous = self.leader_id
            if previous and previous != self.name and previous != leader:
                self.logger.event("LEADER_FAILURE_DETECTED", {"previous_leader": previous})
            self._install_leader(leader)
            if leader == self.name and previous != self.name:
                for peer in self.peers.values():
                    if peer["name"] == self.name:
                        continue
                    try:
                        request(peer, "COORDINATOR", {"leader": self.name}, self.logger)
                    except NET_ERRORS:
                        pass
            self._stop.wait(0.2)

    def _replicate(self) -> bool:
        # Called under _state_lock. A grant is visible to the client only after
        # a majority has the holder snapshot (all live peers are attempted).
        acknowledged = 1
        for peer in self.peers.values():
            if peer["name"] == self.name:
                continue
            try:
                reply = request(peer, "REPLICATE", {"leader": self.name, "state": dict(self.lock_state)}, self.logger)
                acknowledged += reply.get("status") == "REPLICATED"
            except NET_ERRORS:
                pass
        return acknowledged >= len(self.peers) // 2 + 1

    def _handle(self, kind: str, body: dict) -> dict:
        if kind == "standin.configure":
            with self._state_lock:
                if self._monitor is not None:
                    return {"error": "membership already configured"}
                self.peers = {peer["name"]: peer for peer in body["peers"]}
                if self.name not in self.peers or len(self.peers) != 3:
                    raise ValueError("stand-in requires exactly three distinct coordinators")
                self._monitor = threading.Thread(target=self._elect, daemon=True)
                self._monitor.start()
            return {"status": "CONFIGURED"}
        if kind == "ELECTION":
            return {"status": "OK", "node": self.name, "priority": self.priority}
        if kind == "COORDINATOR":
            leader = body["leader"]
            if leader not in self.peers or self.peers[leader]["priority"] <= self.priority:
                return {"error": "coordinator announcement is not from a higher-priority peer"}
            self._install_leader(leader)
            return {"status": "ACK"}
        with self._state_lock:
            if kind == "standin.status":
                return {"node": self.name, "leader": self.leader_id, "lock": dict(self.lock_state)}
            if kind == "REPLICATE":
                state = body["state"]
                if body["leader"] not in self.peers:
                    return {"error": "unknown leader"}
                if state["version"] < self.lock_state["version"]:
                    return {"error": "stale state"}
                if state["version"] == self.lock_state["version"] and state != self.lock_state:
                    return {"error": "conflicting state version"}
                self.lock_state = dict(state)
                self.logger.event("LOCK_STATE_REPLICATED", {"leader": body["leader"], **state})
                return {"status": "REPLICATED"}
            if kind not in ("REQUEST", "RELEASE"):
                return {"error": f"unknown stand-in message: {kind}"}
            if self.leader_id != self.name:
                return {"status": "REDIRECT", "leader": self.leader_id}
            holder, request_id = body["client"], body["request_id"]
            if kind == "REQUEST":
                if self.lock_state["holder"] is not None:
                    if (self.lock_state["holder"], self.lock_state["request_id"]) != (holder, request_id):
                        self.logger.event("LOCK_DENIED", {"client": holder, "holder": self.lock_state["holder"]})
                        return {"status": "DENIED", "holder": self.lock_state["holder"]}
                else:
                    version = self.lock_state["version"] + 1
                    self.lock_state.update(holder=holder, request_id=request_id,
                                           token=f"{self.name}:{version}", version=version)
                if not self._replicate():
                    return {"status": "RETRY", "reason": "holder state not replicated to majority"}
                self.logger.event("LOCK_GRANTED", {"client": holder, "token": self.lock_state["token"]})
                return {"status": "GRANT", "token": self.lock_state["token"]}
            token = body["token"]
            if token == self.lock_state["last_released"]:
                return {"status": "RELEASED"}  # lost reply; safe duplicate release
            if (holder, request_id, token) != (self.lock_state["holder"], self.lock_state["request_id"],
                                                self.lock_state["token"]):
                return {"status": "REJECTED", "reason": "release does not match current grant"}
            self.lock_state.update(holder=None, request_id=None, token=None,
                                   version=self.lock_state["version"] + 1, last_released=token)
            if not self._replicate():
                return {"status": "RETRY", "reason": "release state not replicated to majority"}
            self.logger.event("LOCK_RELEASED", {"client": holder, "token": token})
            return {"status": "RELEASED"}

    def handle(self, conn, message, fmt, peer) -> bool:
        try:
            body = self._handle(message["type"], message.get("payload") or {})
        except (KeyError, ValueError, TypeError) as exc:
            body = {"error": str(exc)}
        reply_type = "GRANT" if message["type"] == "REQUEST" and body.get("status") == "GRANT" else message["type"] + ".reply"
        send_message(conn, make_envelope(reply_type, self.name, body,
                                         correlation_id=message["id"], receiver=message["sender"]),
                     self.logger, peer, fmt)
        return False

    def stop(self) -> None:
        super().stop()
        if self._monitor:
            self._monitor.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--priority", required=True, type=int)
    parser.add_argument("--ready", required=True, type=Path)
    args = parser.parse_args()
    node = StandinCoordinator(args.name, args.priority).start()
    try:
        write_signal(args.ready, {"name": args.name, "host": node.host, "port": node.port,
                                  "priority": args.priority}, node.logger, "control.ready")
        threading.Event().wait()
    finally:
        node.stop()


if __name__ == "__main__":
    main()
