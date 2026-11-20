"""Leader crash during a critical section, with the group's real algorithms (UNG-105 / UNG-120..122).

    python3 -m src.communication.failure_test --output logs/milestone4-failure

Five ``CoordinationNode`` processes (node-A..node-E, ids 1..5) run main's Bully
election (election.py) and Ricart-Agrawala mutual exclusion (mutex.py) around
the ``SharedResource`` (resource.py). A driver process (``failure-driver``)
starts them, observes them over the same framed, Lamport-stamped messages and
injects the failure:

1. node-A starts an election; node-E (highest id) becomes leader.
2. node-E enters the critical section, updates the shared resource once and
   stays inside (it never releases).
3. node-C and node-D request the critical section; node-E defers both replies.
4. The driver SIGKILLs node-E while it is inside the critical section.
5. The heartbeat monitors on A..D notice; Bully re-elects node-D.
6. Lock recovery: C and D see their pending request to node-E fail and treat the
   dead peer as having granted (mutex.py fault handling); they then order
   themselves by (request lc, name) and finish their updates one at a time.
7. The new leader node-D reads the resource back: value = 1 + 2 x UPDATES, no
   overlapping access, history 1..N in order; critical-section intervals
   (node-E's ends at the kill) never overlap.

Every node writes ``nodes/<node>.jsonl``; the run ends with ``merge_logs`` producing
``ordered.jsonl`` in (lc, node) order plus ``summary.json``. The output directory
must be new. Only the child processes started here are ever signalled.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .merge_logs import check_causality, merge_logs
from .node import CoordinationNode
from .resource import SharedResource
from .rpc import RPCClient
from .signal_file import read_signal, write_signal

ROOT = Path(__file__).resolve().parents[2]
NODES = [(f"node-{c}", i) for i, c in enumerate("ABCDE", 1)]
LEADER, NEW_LEADER = "node-E", "node-D"
CONTENDERS = ("node-C", "node-D")
UPDATES = 3


# ============================================================ worker process (one coordination node)

def worker(name: str, node_id: int, ready: Path) -> None:
    node = CoordinationNode(name, node_id).start()
    st = {"resource": None, "intervals": [], "busy": False, "holding": False}

    def update_once() -> dict:
        host, port = st["resource"]
        with RPCClient(node.name, host, port, logger=node.logger) as c:   # same node, same clock
            return c.call("resource.update", node=node.name)

    def h_setup(body: dict) -> dict:
        node.set_peers(body["peers"])
        st["resource"] = tuple(body["resource"])
        node.election.start_monitor(interval=body.get("monitor", 0.3))
        return {"ok": True}

    def h_elect(body: dict) -> dict:
        threading.Thread(target=node.election.start_election, daemon=True).start()
        return {"ok": True}

    def h_hold(body: dict) -> dict:
        """Enter the CS, update once, then stay inside until this process is killed."""
        def run():
            node.mutex.acquire()
            enter = time.monotonic()
            update_once()
            st["intervals"].append({"client": node.name, "enter": enter, "exit": None})
            st["holding"] = True
            node.logger.info(f"{node.name} is working inside the critical section (does not release)",
                             failure={"action": "holding", "node": node.name})
            threading.Event().wait()
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def h_work(body: dict) -> dict:
        """Do ``updates`` protected updates, recording each critical-section interval."""
        def run():
            try:
                for _ in range(int(body["updates"])):
                    node.mutex.acquire()
                    enter = time.monotonic()
                    try:
                        update_once()
                    finally:
                        st["intervals"].append({"client": node.name, "enter": enter, "exit": time.monotonic()})
                        node.mutex.release()
            finally:
                st["busy"] = False
        st["busy"] = True
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def h_status(body: dict) -> dict:
        return {"name": node.name, "leader": node.election.leader_name, "mutex": node.mutex.state,
                "entries": node.mutex.entries, "busy": st["busy"], "holding": st["holding"],
                "intervals": list(st["intervals"])}

    def h_verify(body: dict) -> dict:
        """Run by the (new) leader: read the shared resource back."""
        host, port = st["resource"]
        with RPCClient(node.name, host, port, logger=node.logger) as c:
            state = c.call("resource.state")
        node.logger.info(f"leader {node.name} reads the resource: value={state['value']}, "
                         f"updates={state['updates']}, violations={len(state['violations'])}",
                         failure={"action": "verify", "node": node.name})
        return state

    for kind, fn in (("demo.setup", h_setup), ("demo.elect", h_elect), ("demo.hold", h_hold),
                     ("demo.work", h_work), ("demo.status", h_status), ("demo.verify", h_verify)):
        node.register(kind, fn)
    write_signal(ready, {"name": name, "id": node_id, "host": node.host, "port": node.port},
                 node.logger, "control.ready")
    threading.Event().wait()


# ============================================================ driver

def check_intervals(intervals: list[dict], holder: str) -> None:
    """Critical-section intervals (one system-wide monotonic clock) must never overlap."""
    if len(intervals) < 2 or holder not in {item["client"] for item in intervals}:
        raise AssertionError("need the original holder and a completed contender")
    if len({item["client"] for item in intervals}) < 2:
        raise AssertionError("need at least two different clients")
    ordered = sorted(intervals, key=lambda item: item["enter"])
    previous_exit = -math.inf
    for item in ordered:
        start, end = item["enter"], item["exit"]
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise AssertionError("invalid critical-section interval")
        if start < previous_exit:
            raise AssertionError(f"overlapping critical sections: mutual exclusion violated at {item}")
        previous_exit = end


class Cluster:
    """The driver's view: owns the child processes and talks to them as node ``failure-driver``."""

    def __init__(self, output: Path):
        self.output = output
        self.driver = CoordinationNode("failure-driver", 0).start()   # not a member: nobody has it as a peer
        self.log = self.driver.logger
        self.processes: dict[str, subprocess.Popen] = {}
        self.peers: dict[str, dict] = {}
        self._streams = []

    def spawn(self, env: dict, timeout: float) -> None:
        for name, node_id in NODES:
            ready = self.output / f"{name}.ready.json"
            stream = (self.output / f"{name}.out").open("w", encoding="utf-8")
            self._streams.append(stream)
            self.processes[name] = subprocess.Popen(
                [sys.executable, "-m", "src.communication.failure_test", "--worker", name,
                 "--id", str(node_id), "--ready", str(ready)],
                cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout
            while not ready.exists():
                if self.processes[name].poll() is not None:
                    raise RuntimeError(f"{name} exited with {self.processes[name].returncode}; see {name}.out")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{name} did not become ready")
                time.sleep(0.02)
            info = read_signal(ready, self.log)          # file signal carries node -> driver causality
            self.peers[name] = {"name": info["name"], "id": info["id"], "host": info["host"], "port": info["port"]}

    def call(self, name: str, kind: str, body: dict | None = None) -> dict:
        return self.driver.call(self.peers[name], kind, body or {})

    def status(self, name: str) -> dict:
        return self.call(name, "demo.status")

    def wait_until(self, what: str, cond, timeout: float, every: float = 0.1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = cond()
            if result:
                return result
            time.sleep(every)
        raise TimeoutError(f"timed out waiting for {what}")

    def leaders(self, names) -> dict:
        return {n: self.status(n)["leader"] for n in names}

    def stop(self) -> None:
        for proc in self.processes.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in self.processes.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for stream in self._streams:
            stream.close()
        self.driver.stop()


def say(text: str) -> None:
    print(text, flush=True)


def run_failure_test(output: Path, timeout: float = 20, updates: int = UPDATES, verbose: bool = False) -> dict:
    """Run the scenario; always stop the children and keep the logs, also on failure."""
    out = say if verbose else (lambda _t: None)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    capture_env = {"COMM_QUIET": "1", "COMM_LOG_FILE": str(output / "messages.jsonl"),
                   "COMM_NODE_LOG_DIR": str(output / "nodes")}
    previous = {key: os.environ.get(key) for key in capture_env}
    os.environ.update(capture_env)
    summary: dict = {"status": "failed"}
    cluster = resource = None
    try:
        resource = SharedResource(work_time=0.05).start()
        cluster = Cluster(output)
        log = cluster.log
        log.event("FAILURE_TEST_STARTED", "5 coordination nodes, leader crash during a critical section")
        cluster.spawn({**os.environ}, timeout)
        survivors = [n for n, _ in NODES if n != LEADER]
        for name in cluster.peers:
            cluster.call(name, "demo.setup", {"peers": list(cluster.peers.values()),
                                              "resource": [resource.host, resource.port]})
        out(f"[1] started {len(cluster.peers)} node processes: "
            + ", ".join(f"{n}(id {p['id']}, pid {cluster.processes[n].pid})" for n, p in cluster.peers.items()))

        cluster.call("node-A", "demo.elect")
        leaders = cluster.wait_until("first election", lambda: (lambda l: l if set(l.values()) == {LEADER} else None)(
            cluster.leaders(cluster.peers)), timeout)
        log.event("LEADER_OBSERVED", f"all nodes agree: leader {LEADER}", failure={"leader": LEADER})
        out(f"[2] Bully election started by node-A -> leader {LEADER} (agreed by all: {sorted(leaders)})")

        cluster.call(LEADER, "demo.hold")
        held = cluster.wait_until("leader inside the critical section",
                                  lambda: (lambda s: s if s["mutex"] == "HELD" and s["holding"] else None)(
                                      cluster.status(LEADER)), timeout)
        holder_enter = held["intervals"][0]["enter"]
        log.event("CRITICAL_SECTION_OBSERVED", f"{LEADER} is inside the critical section",
                  failure={"holder": LEADER, "mutex": held["mutex"]})
        out(f"[3] {LEADER} (the leader) entered the critical section, updated the resource "
            f"(value={resource.value}) and stays inside")

        for name in CONTENDERS:
            cluster.call(name, "demo.work", {"updates": updates})
        out(f"[4] {' and '.join(CONTENDERS)} request the critical section ({updates} updates each); "
            f"{LEADER} defers its replies")
        time.sleep(1.5)                                    # let them queue up behind the holder

        log.event("LEADER_KILL_REQUESTED", f"SIGKILL {LEADER} while it holds the critical section",
                  failure={"leader": LEADER, "pid": cluster.processes[LEADER].pid})
        killed_at = time.monotonic()        # node-E is inside until it dies, which is no earlier than this
        cluster.processes[LEADER].send_signal(signal.SIGKILL)
        code = cluster.processes[LEADER].wait(timeout=5)
        log.event("LEADER_KILLED", f"{LEADER} exited with {code}", failure={"leader": LEADER, "returncode": code})
        out(f"[5] SIGKILL -> {LEADER} (pid {cluster.processes[LEADER].pid}) exited with {code} "
            f"while inside the critical section")

        leaders = cluster.wait_until("re-election", lambda: (lambda l: l if set(l.values()) == {NEW_LEADER} else None)(
            cluster.leaders(survivors)), timeout)
        log.event("NEW_LEADER_OBSERVED", f"survivors agree: leader {NEW_LEADER}",
                  failure={"leader": NEW_LEADER, "previous": LEADER})
        out(f"[6] heartbeat noticed the crash; Bully re-election -> new leader {NEW_LEADER} "
            f"(agreed by {', '.join(sorted(leaders))})")

        done = cluster.wait_until("contenders to finish", lambda: (lambda s: s if all(
            not x["busy"] and x["entries"] == updates for x in s.values()) else None)(
            {n: cluster.status(n) for n in CONTENDERS}), timeout)
        intervals = [{"client": LEADER, "enter": holder_enter, "exit": killed_at}]
        for name in CONTENDERS:
            intervals += done[name]["intervals"]
        first_after = min(i["enter"] for i in intervals if i["client"] != LEADER) - killed_at
        log.event("LOCK_RECOVERED", "contenders treated the dead holder as granted and finished",
                  failure={"policy": "dead peer counts as granted (mutex.py)",
                           "entries": {n: done[n]["entries"] for n in CONTENDERS}})
        out(f"[7] lock recovered: first contender entered {first_after * 1000:.1f} ms after the SIGKILL; "
            f"entries {', '.join(f'{n}={done[n]['entries']}' for n in CONTENDERS)}")

        check_intervals(intervals, LEADER)
        verified = cluster.call(NEW_LEADER, "demo.verify")
        expected = 1 + updates * len(CONTENDERS)
        history = [h["after"] for h in resource.history]
        if verified["value"] != expected or verified["violations"] or history != list(range(1, expected + 1)):
            raise AssertionError(f"resource inconsistent: {verified}, history {history}")
        log.event("MUTUAL_EXCLUSION_VERIFIED", f"{len(intervals)} critical sections, no overlap; "
                  f"resource value {verified['value']} == {expected}, 0 violations",
                  failure={"intervals": len(intervals), "value": verified["value"]})
        out(f"[8] mutual exclusion holds: {len(intervals)} critical sections, none overlapping; "
            f"{NEW_LEADER} reads value={verified['value']} (expected {expected}), "
            f"violations={len(verified['violations'])}, history {history}")
        summary = {"status": "passed", "old_leader": LEADER, "new_leader": NEW_LEADER,
                   "leader_returncode": code, "resource": {"value": verified["value"], "expected": expected,
                                                         "violations": verified["violations"],
                                                         "history": resource.history},
                   "critical_sections": [{**i, "enter": round(i["enter"] - holder_enter, 4),
                                          "exit": round(i["exit"] - holder_enter, 4)} for i in intervals]}
        log.event("FAILURE_TEST_COMPLETE", "passed")
        return summary
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        if cluster:
            cluster.log.event("FAILURE_TEST_FAILED", summary["error"])
        raise
    finally:
        try:
            if cluster:
                cluster.stop()
            if resource:
                resource.stop()
        finally:
            try:
                events = merge_logs([output / "nodes"], output / "ordered.jsonl")
                summary["events"] = len(events)
                summary["causal_pairs_checked"] = check_causality(events)
                (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
                out(f"[9] merged {len(events)} events from {len({e['node'] for e in events})} per-node logs into "
                    f"{output / 'ordered.jsonl'}; {summary['causal_pairs_checked']} send/receive pairs in causal order")
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("logs/milestone4-failure"))
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--updates", type=int, default=UPDATES)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--id", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--ready", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.id, args.ready)
        return
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive and finite")
    summary = run_failure_test(args.output, args.timeout, args.updates, verbose=True)
    print(f"RESULT: {summary['status']} - leader {summary['old_leader']} killed (exit {summary['leader_returncode']}), "
          f"{summary['new_leader']} elected, resource {summary['resource']['value']}/{summary['resource']['expected']}, "
          f"{len(summary['critical_sections'])} non-overlapping critical sections")


if __name__ == "__main__":
    main()
