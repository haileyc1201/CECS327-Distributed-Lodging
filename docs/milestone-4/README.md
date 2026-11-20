# Milestone 4: Coordination

This milestone puts Josiah's coordination layer and Tom's clock, event-ordering and failure-test work together in one system. It uses Python 3.10+ and the standard library only.

## Who did what

| Part | Source | Files |
|---|---|---|
| Lamport clock, Bully election, Ricart-Agrawala mutex, shared resource, coordination demo, `test_coordination.py` | Josiah (main, `f42f976`) | `clock.py`, `election.py`, `mutex.py`, `node.py`, `resource.py`, `coordination_demo.py` |
| Clocks on every message: thread safety, rejecting invalid stamps, one clock per node name, a fresh stamp on every resend, local events tick (UNG-100/108/109) | Tom, folded into main's `clock.py` and `lc` field | `clock.py`, `transport.py`, `msglog.py`, `signal_file.py` |
| One structured log per node plus `merge_logs.py` total order `(lc, node)` (UNG-101/110/111) | Tom | `msglog.py`, `merge_logs.py`, `clock_demo.py` |
| Leader-crash test during a critical section, lock recovery, captured logs (UNG-105/120/121/122) | Tom, now running on main's real Bully and Ricart-Agrawala code (the temporary stand-in coordinator is gone) | `failure_test.py` |

## Clock and log design

- **One clock, one field.** Each node has one `LamportClock` (main's `clock.py`). Every envelope carries `lc`.
  - Send: `t = t + 1`, and the value goes on a *copy* of the envelope. That way a forwarded or fanned-out envelope gets a new stamp each time.
  - Receive: `t = max(t, lc) + 1`, applied before the message is handled.
- **Safety additions from Tom's `lamport.py`.**
  - All clock operations take a lock.
  - Negative, boolean, float and string stamps raise `ValueError`, and the clock doesn't move.
  - The transport is strict: a frame without `lc` is rejected, and the server logs and drops it.
  - `update(None)` still counts as a local event, so main's API and tests are unchanged.
- **Atomic logging.** Each node has a re-entrant `event_lock`, so advancing the clock and writing the log entry happen as one step. Two threads can't log the same `lc`.
  - Loggers are shared per node name within a process, so a short-lived `RPCClient` or `lookup_via` helper doesn't restart the node's time.
  - Local events tick too: INFO, `LOCAL_DISPATCH` and `LOOKUP_START`.
  - A mutex request is logged with exactly its request timestamp.
  - A fresh node logs its "listening" line at `lc 0`, its initial state.
- **Per-node logs.** Every entry is written to `logs/messages.jsonl` and to `logs/nodes/<node>.jsonl`. You can override these with `COMM_LOG_FILE` and `COMM_NODE_LOG_DIR`. The entry format is main's: `{ts, lc, node, event, ...}`.
- **Total order.** `merge_logs` sorts by `(lc, node)`, using Lamport time with ties broken by node name, never wall-clock time.
  - It rejects duplicate keys, malformed lines (reporting the file and line), empty input, and an output file that would overwrite an input.
  - `check_causality` confirms that every RECV comes after its SEND.
  - `--table N --since LC` prints a readable table.

## Failure test (`failure_test.py`)

The test runs five real `CoordinationNode` processes (node-A to node-E, ids 1 to 5) plus a driver process that owns the `SharedResource`. Steps:

1. node-A starts a Bully election, and node-E wins.
2. node-E enters the Ricart-Agrawala critical section, updates the resource once, and stays inside.
3. node-C and node-D request the critical section, and node-E defers both.
4. The driver sends **SIGKILL** to node-E (exit code -9) while it is inside.
5. The heartbeat monitors notice, and Bully re-elects **node-D**.
6. **Lock recovery:** the pending requests to node-E fail, so node-C and node-D treat the dead peer as having granted (the crash handling in `mutex.py`). They then go one at a time in `(lc, name)` order.
7. **Checks:**
   - Critical-section intervals never overlap. They are measured on the shared monotonic clock, and node-E's interval ends at the kill.
   - The new leader node-D reads `value = 1 + 2 x updates` with 0 violations, and the history runs 1..N in order.
   - The merged log is sorted and unique, and the causality checks pass.

Ricart-Agrawala doesn't have a lock server, so no lock state needs to be handed to the new leader. Recovery means the survivors stop waiting for the dead holder. The new leader is the one that verifies the resource.

**Limitations:**

- Events that aren't causally related can land in either order in the Lamport-ordered log. For example, node-E's `defers` lines and the driver's kill are concurrent.
- A crash is detected through a failed connection, not a message, so it has no Lamport stamp.
- This is a crash-stop, localhost, coursework model. It has no partitions, no rejoin and no persistence.

## Run

```bash
python3 -m src.communication.coordination_demo
python3 -m src.communication.clock_demo --output logs/milestone4-demo
python3 -m src.communication.failure_test --output logs/milestone4-failure
python3 -m src.communication.merge_logs logs/milestone4-failure/nodes -o /tmp/ordered.jsonl --since 100 --table 40
python3 -m unittest discover -s tests -t . -v
```

The capture directories must be new.

## Evidence from real runs of the merged code

- `samples/clocks/`: three ring peer processes and a client.
  - Contents: `run-output.txt`, raw `nodes/*.jsonl`, `ordered.jsonl` and `summary.json`.
  - The lookup route was clock-A -> clock-C -> clock-B.
  - Every receive came after its send.
- `samples/failure/`: the failure test.
  - Contents: `run-output.txt`, `nodes/*.jsonl` for 7 nodes, `ordered.jsonl` with 566 events and `summary.json`.
  - Re-merging `nodes/` reproduces `ordered.jsonl` byte for byte.
- `test-results.txt`: 53 tests, all OK.
- `screenshots/`:
  - `01_full_test_suite.png`
  - `02_tom_tests.png`
  - `03_clock_ordering_demo.png`
  - `04_merged_ordered_log.png`
  - `05_failure_test_leader_killed.png`
