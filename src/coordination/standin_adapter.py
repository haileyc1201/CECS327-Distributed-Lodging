"""Real local-process adapter for the TEMPORARY stand-in coordinator.

Replace this factory with an adapter for Josiah's coordinator without changing
the failure-test orchestration, assertions, or logical log capture.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.communication.clock_demo import ROOT, wait_ready
from src.communication.msglog import MessageLogger
from src.communication.signal_file import read_signal, write_signal
from .standin_coordinator import NET_ERRORS, request


class StandinAdapter:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self.streams = []
        self.peers: list[dict] = []
        self.killed: str | None = None

    def _spawn(self, name: str, module: str, arguments: list[str]) -> subprocess.Popen:
        stream = (self.directory / f"{name}.out").open("w", encoding="utf-8")
        self.streams.append(stream)
        process = subprocess.Popen([sys.executable, "-m", module, *arguments], cwd=ROOT,
                                   env=dict(os.environ), stdout=stream, stderr=subprocess.STDOUT)
        self.processes[name] = process
        return process

    def start(self, node_log_dir: Path, logger: MessageLogger) -> None:
        self.directory = node_log_dir.parent
        self.logger = logger
        for priority in (1, 2, 3):
            name = f"standin-{priority}"
            ready = self.directory / f"{name}.ready.json"
            process = self._spawn(name, "src.coordination.standin_coordinator",
                                  ["--name", name, "--priority", str(priority), "--ready", str(ready)])
            self.peers.append(wait_ready(process, ready, logger))
        write_signal(self.directory / "peers.json", {"peers": self.peers}, logger, "control.membership")
        for peer in self.peers:
            reply = request(peer, "standin.configure", {"peers": self.peers}, logger)
            if reply.get("status") != "CONFIGURED":
                raise AssertionError(reply)
        self._wait(lambda: self._agreed_leader() == "standin-3", 10, "initial election did not converge")

    @staticmethod
    def _wait(condition, timeout: float, message: str):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = condition()
            if result:
                return result
            time.sleep(0.03)
        raise TimeoutError(message)

    def _statuses(self) -> list[dict]:
        statuses = []
        for peer in self.peers:
            if self.processes[peer["name"]].poll() is not None:
                continue
            try:
                statuses.append(request(peer, "standin.status", {}, self.logger))
            except NET_ERRORS:
                pass
        return statuses

    def _agreed_leader(self) -> str | None:
        statuses = self._statuses()
        live = [peer for peer in self.peers if self.processes[peer["name"]].poll() is None]
        leaders = {status.get("leader") for status in statuses}
        if len(statuses) != len(live) or len(leaders) != 1:
            return None
        leader = next(iter(leaders))
        return leader if leader in {peer["name"] for peer in live} else None

    def leader(self) -> str:
        leader = self._agreed_leader()
        if not leader:
            raise AssertionError("cluster has not agreed on a live leader")
        return leader

    def _start_client(self, name: str, hold: bool = False) -> subprocess.Popen:
        args = ["--name", name, "--peers", str(self.directory / "peers.json"),
                "--directory", str(self.directory)]
        if hold:
            args.append("--hold")
        return self._spawn(name, "src.coordination.standin_client", args)

    def enter_critical_section(self, holder: str, timeout: float) -> None:
        process = self._start_client(holder, hold=True)
        wait_ready(process, self.directory / f"{holder}.entered.json", self.logger, timeout)

    def in_critical_section(self, holder: str) -> bool:
        active = self.directory / "critical-section.active"
        return (self.processes[holder].poll() is None and active.exists()
                and active.read_text(encoding="utf-8") == holder)

    def kill_leader(self, leader: str) -> None:
        process = self.processes[leader]  # only an owned child; never arbitrary PID
        if process.poll() is not None:
            raise AssertionError("leader already exited before the injected crash")
        process.kill()  # SIGKILL: no graceful shutdown and no in-memory lock cleanup
        process.wait(timeout=5)
        self.killed = leader

    def wait_for_new_leader(self, old_leader: str, timeout: float) -> str:
        def replacement():
            leader = self._agreed_leader()
            return leader if leader and leader != old_leader else None
        return self._wait(replacement, timeout, "replacement leader was not elected")

    def wait_for_lock_recovery(self, leader: str, timeout: float) -> dict:
        def restored():
            states = self._statuses()
            own = next((state for state in states if state["node"] == leader), None)
            if own and own["lock"]["holder"] == "failure-holder" and self.in_critical_section("failure-holder"):
                return {"policy": "restore", "leader": leader, "holder_still_active": True,
                        "state": own["lock"], "standin": True}
            return None
        return self._wait(restored, timeout, "live holder's grant was not restored")

    def exercise_contenders(self, holder: str, timeout: float) -> list[dict]:
        contender = "failure-contender"
        process = self._start_client(contender)
        # Observe a real DENIED response from the replacement while old CS is
        # active. Only then allow that holder to finish and RELEASE to it.
        reply = wait_ready(process, self.directory / f"{contender}.waiting.json", self.logger, timeout)
        if reply["status"] != "DENIED" or reply["holder"] != holder or not self.in_critical_section(holder):
            raise AssertionError("replacement did not protect the live old holder")
        self.logger.event("CONTENDER_BLOCKED_AFTER_FAILOVER", {"holder": holder, "contender": contender})
        write_signal(self.directory / f"{holder}.release", {}, self.logger, "control.release")
        intervals = []
        for name in (holder, contender):
            child = self.processes[name]
            child.wait(timeout=timeout)
            if child.returncode != 0:
                raise AssertionError(f"{name} failed (exit {child.returncode}); see {name}.out")
            intervals.append(read_signal(self.directory / f"{name}.interval.json", self.logger))
        ledger = [json.loads(line) for line in (self.directory / "shared-resource.jsonl").read_text().splitlines()]
        if [entry["client"] for entry in ledger] != [holder, contender]:
            raise AssertionError("protected resource operations are missing or out of order")
        statuses = self._statuses()
        if any(state["lock"]["holder"] is not None for state in statuses):
            raise AssertionError("a live coordinator retained a stuck lock")
        return intervals

    def stop(self) -> None:
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in self.streams:
            stream.close()


def create_adapter() -> StandinAdapter:
    return StandinAdapter()
