"""Real leader-crash test through a replaceable coordinator interface (UNG-105).

The default adapter runs a clearly labeled temporary stand-in until Josiah's
UNG-102 / UNG-103 land. This harness implements no election/lock protocol.
It verifies actual child processes, holder recovery, and exclusion intervals.

    python3 -m src.communication.failure_test --adapter standin \
        --output logs/milestone4-failure

The adapter must control only the local child processes it started, never an
unrelated service. See docs/milestone-4/README.md for the integration contract.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
from pathlib import Path
from typing import Protocol

from .merge_logs import merge_logs
from .msglog import MessageLogger


class RecoveryAdapter(Protocol):
    """Hooks for Josiah's UNG-102 / UNG-103 implementation (not a protocol implementation)."""

    def start(self, node_log_dir: Path, logger: MessageLogger) -> None:
        """Start isolated local nodes; give ALL children COMM_NODE_LOG_DIR.

        Use the supplied logger for driver-side TCP requests so observations
        and node messages share causal logical time. Raise if not ready.
        """
        ...

    def leader(self) -> str:
        """Return the currently agreed coordinator id."""
        ...

    def enter_critical_section(self, holder: str, timeout: float) -> None:
        """Start a real holder process; return only once its CS is active.

        Keep it in the CS until after kill_leader, so leader death really
        happens mid-CS. A status read alone is not a critical section.
        """
        ...

    def in_critical_section(self, holder: str) -> bool:
        ...

    def kill_leader(self, leader: str) -> None:
        """Force-stop and wait for the owned leader child, not graceful leave."""
        ...

    def wait_for_new_leader(self, old_leader: str, timeout: float) -> str:
        """Observe actual election convergence; timeout if no replacement."""
        ...

    def wait_for_lock_recovery(self, leader: str, timeout: float) -> dict:
        """Return {policy: reset|restore, ...observed details} after recovery.

        UNG-120 plugs in here: restore the live holder OR fence/revoke the old
        grant and establish quiescence BEFORE resetting. Empty lock state on
        a new coordinator alone is NOT safe (old holder might still be active).
        """
        ...

    def exercise_contenders(self, holder: str, timeout: float) -> list[dict]:
        """Complete the old holder and >=1 contender; prove no stuck/double grant.

        Return actual {client, enter, exit} intervals including the surviving
        old holder's original CS and each contender, on the same local
        monotonic clock. Check resource conflicts too (UNG-104 integration).
        Timeout if a client cannot finish. Never synthesize intervals.
        """
        ...

    def stop(self) -> None:
        """Always stop/join every owned child, even after assertion failure."""
        ...


def check_intervals(intervals: list[dict], holder: str) -> None:
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
            raise AssertionError("overlapping critical sections: mutual exclusion violated")
        previous_exit = end


def run_failure_test(adapter: RecoveryAdapter, output: Path, timeout: float = 15) -> dict:
    """Orchestrate a real process test; always retain available logs on failure."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    capture_env = {"COMM_QUIET": "1", "COMM_LOG_FILE": str(output / "messages.jsonl"),
                   "COMM_NODE_LOG_DIR": str(output / "nodes")}
    previous = {key: os.environ.get(key) for key in capture_env}
    os.environ.update(capture_env)
    logger = MessageLogger("failure-driver")
    summary = {"status": "failed", "adapter": type(adapter).__name__}
    try:
        logger.event("FAILURE_TEST_STARTED")
        adapter.start(output / "nodes", logger)
        old = adapter.leader()
        holder = "failure-holder"
        adapter.enter_critical_section(holder, timeout)
        if not adapter.in_critical_section(holder):
            raise AssertionError("holder is not in a critical section; refusing to kill leader")
        logger.event("CRITICAL_SECTION_OBSERVED", {"holder": holder, "leader": old})
        logger.event("LEADER_KILL_REQUESTED", {"leader": old})
        adapter.kill_leader(old)
        logger.event("LEADER_STOPPED", {"leader": old})
        new = adapter.wait_for_new_leader(old, timeout)
        if not new or new == old:
            raise AssertionError("no replacement leader was elected")
        logger.event("NEW_LEADER_OBSERVED", {"leader": new, "previous": old})
        recovery = adapter.wait_for_lock_recovery(new, timeout)
        if recovery.get("policy") not in ("reset", "restore"):
            raise AssertionError("adapter did not report its lock recovery policy")
        logger.event("LOCK_RECOVERY_OBSERVED", recovery)
        intervals = adapter.exercise_contenders(holder, timeout)
        check_intervals(intervals, holder)
        logger.event("MUTUAL_EXCLUSION_VERIFIED", {"intervals": intervals})
        summary = {"status": "passed", "old_leader": old, "new_leader": new,
                   "recovery": recovery, "critical_sections": intervals}
        logger.event("FAILURE_TEST_COMPLETE", summary)
        return summary
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        logger.event("FAILURE_TEST_FAILED", {"error": summary["error"]})
        raise
    finally:
        try:
            adapter.stop()
        except Exception as exc:
            summary.update(status="failed", error=f"cleanup failed: {type(exc).__name__}: {exc}")
            logger.event("FAILURE_TEST_CLEANUP_FAILED", {"error": summary["error"]})
            raise
        finally:
            try:
                merge_logs([output / "nodes"], output / "ordered.jsonl")
                (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", default="standin", help="standin (temporary) or module:factory implementing RecoveryAdapter")
    parser.add_argument("--output", type=Path, default=Path("logs/milestone4-failure"))
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive and finite")
    if args.adapter == "standin":
        print("NOTE: real processes using TEMPORARY stand-in; replace with Josiah's UNG-102/103 adapter.")
        args.adapter = "src.coordination.standin_adapter:create_adapter"
    module, separator, factory = args.adapter.partition(":")
    if not separator or not module or not factory:
        parser.error("--adapter must be module:factory")
    adapter = getattr(importlib.import_module(module), factory)()
    print(json.dumps(run_failure_test(adapter, args.output, args.timeout), indent=2))


if __name__ == "__main__":
    main()
