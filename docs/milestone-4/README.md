# Milestone 4: Tom's coordination parts

Python 3.10+, standard library only. Built on the group's Python implementation
at `2e3523c`; no web deployment or DNS changes.

## Scope / issue map

| Issues | Implementation / evidence |
|---|---|
| UNG-100, UNG-108 | `lamport.py`: per-node thread-safe tick/send/receive; lower/equal/higher receive tests |
| UNG-109 | `codec.py`, `transport.py`, `signal_file.py`: logical timestamps on all M4 messages and file-control signals |
| UNG-101, UNG-110 | `msglog.py`: one structured event format and one file per logical node |
| UNG-111 | `merge_logs.py` + raw per-node and ordered samples below |
| UNG-105, UNG-121 | `failure_test.py` + real child-process `standin_adapter.py`: kill coordinator in an active CS |
| UNG-120 | `standin_coordinator.py`: replicate holder state before GRANT; restore live holder after election |
| UNG-122 | `samples/failure/`: real ordered failure/election/recovery trace and result |

**The coordinator is a clearly labeled, replaceable stand-in**, not a claim that
Josiah's UNG-102/103 or Andrew's UNG-104 are implemented. It lives separately in
`src/coordination/`. Their issue status and existing group/ring protocols are not
replaced by this demo. The stand-in should be swapped out when their code lands.
The unframed Milestone 1 service scripts remain historical prototypes; M4 uses
the `src.communication` framed message system and the stand-in adapter.

## Run / reproduce

Run from the repository root. Each capture directory must be NEW; this prevents
mixing logical clocks from different runs and silently overwriting evidence.
Ephemeral localhost ports avoid collisions with existing services.

```bash
# Unit + real integration tests (38 tests, including the SIGKILL scenario)
python3 -m unittest discover -s tests -t . -v

# Three actual ring peer processes, a store and two-hop lookup
python3 -m src.communication.clock_demo --output logs/milestone4-demo

# Three coordinator + two client child processes, driven by a sixth process
python3 -m src.communication.failure_test --adapter standin \
  --output logs/milestone4-failure

# Reproduce the committed ordered failure log from its raw per-node logs
python3 -m src.communication.merge_logs \
  docs/milestone-4/samples/failure/nodes -o /tmp/m4-failure-ordered.jsonl
```

Both capture scripts terminate/join only their own children, including on errors.
A failure raises / exits nonzero and preserves available logs; an existing output
directory is rejected. Runtime `.out` files are diagnostics, not committed samples.

## Clock and message design

Each logical node has one `LamportClock`, initially 0. All logger/helper-client
instances for the same node name in one process share it, so a new RPC connection,
`coordinator_request`, or `lookup_via` does not restart time. Different node names
must be unique across processes within a capture.

* Before each **local logged application event**, `tick()` increments by 1.
  This includes dispatch, local ring dispatch, lookup start/hops, and lock/election
  state transitions. Application code can log further transitions with
  `logger.event(name, details)` or `logger.info(note)`.
* Before each **send**, `send()` increments by 1. The transport stamps a copy of
  the envelope with integer `logical_timestamp` immediately before marshalling.
  Forwarded/reused envelopes get a fresh time on every send. Caller data is not
  mutated. JSON and typed XML preserve the integer.
* On **receive**, before application handling,
  `clock = max(clock, message.logical_timestamp) + 1`. Missing, negative, boolean
  and non-integer times are rejected, not silently converted to 0.
* A shared per-node lock serializes clock updates and log writes across threads.
  Framed RPC, pub-sub, group and ring/lookup calls all pass through these same
  transport functions. Future election/lock message types need no special case.
* Demo readiness, membership, waiting, release and interval files also carry
  stamped envelopes (`signal_file.py`). These control messages communicate real
  causal dependencies, such as CS entry before the driver's kill. Atomic rename
  prevents partial control-file reads.

The original envelope `timestamp` (ISO-8601 UTC wall time) is kept for backwards
compatibility; `logical_timestamp` is the ordering time. In EVENT LOG entries,
`timestamp` is the Lamport integer and `ts` is the old wall-clock string.
Wall time never determines total order.

## Event log / total order

Canonical fields on EVERY event (legacy M2 fields remain alongside them):

```json
{"timestamp":12,"node_id":"ring-A","event":"LOCAL_DISPATCH","details":{"type":"ring.store"}}
```

Default files: `logs/messages.jsonl` (legacy aggregate) and
`logs/nodes/<escaped-node-id>.jsonl` (per-node). Use `COMM_LOG_FILE` and
`COMM_NODE_LOG_DIR` to isolate a run. Do not merge logs from separate process
restarts with the same node id; logical clocks intentionally restart with the
process. The provided capture commands isolate each run automatically.

The merger sorts `(timestamp, node_id)`, where node ids are strings compared
lexicographically. Equal timestamps on different nodes are broken by that id.
Each node's times are strictly increasing, so the pair uniquely orders all events.
Duplicate keys (including passing both the aggregate AND its per-node copies),
malformed records, empty logs, and output-overwriting-input are rejected with a
source-file/line error. The node-name filename escaping prevents path traversal.

Lamport order extends causality; it is NOT a claim about physical ordering of
unrelated events or a synchronized physical clock. Critical-section intervals
are independently measured on the shared local monotonic clock to check overlap.

## Temporary stand-in and recovery choice

The stand-in uses fixed membership with priorities 1, 2, 3. Each peer periodically
sends `ELECTION` to higher-priority peers and receives `OK`. If no higher peer
responds, it announces `COORDINATOR`; otherwise it follows the highest live peer.
On killing `standin-3`, the surviving highest priority is `standin-2`.

The centralized lock protocol is `REQUEST -> GRANT` (or DENIED/REDIRECT/RETRY),
then `RELEASE -> RELEASED`. A grant carries a unique token and request id. A
coordinator serializes state changes and replicates the holder/token/version to
followers before returning GRANT; a majority must acknowledge. It attempts every
live follower. Requests retried with the same id recover the same grant, including
a GRANT reply lost at coordinator failure. A mismatched release cannot release a
current holder; repeated old releases do not clear a newer grant.

**Choice: RESTORE, not blind reset.** The old client is still alive in its CS when
the leader dies. Clearing the new coordinator's lock would let a contender enter
on top of it. Instead the new leader preserves its replicated holder/token, denies
the contender, accepts the old holder's matching release, then grants the contender.
Both surviving coordinators finish with no holder. The protected demo resource is
a local append-only ledger, written only in the granted CS. An exclusive active
marker is an **assertion detector**, not another mutual-exclusion implementation:
if two clients receive conflicting grants it fails immediately instead of blocking
and concealing the bug. Measured CS intervals must also be non-overlapping.

### Explicit failure model / limitations

This is a coursework crash-only stand-in: three fixed local nodes, one fail-stop
coordinator failure, surviving clients, and reliable localhost TCP. It is **not** a
production consensus protocol. It does not promise partition safety, restart/rejoin,
multiple simultaneous failures, dead-client lease reclamation, durable disk recovery,
or Byzantine/authenticated coordination. If the holder itself dies, explicit safe
recovery/leases are future work, not silently solved by clearing the lock. Do not
use this stand-in to claim those properties or replace the team's final algorithm.

## Real recorded evidence

* [Clock demo summary](samples/clocks/summary.json), [stdout](samples/clocks/run-output.txt),
  [raw node logs](samples/clocks/nodes/), [ordered log](samples/clocks/ordered.jsonl):
  94 events from 3 ring peers + a client; listing 101 returned through
  `clock-A -> clock-C -> clock-B` (2 hops).
* [Failure result](samples/failure/summary.json), [stdout](samples/failure/run-output.txt),
  [raw node logs](samples/failure/nodes/), [ordered log](samples/failure/ordered.jsonl),
  [protected ledger](samples/failure/shared-resource.jsonl): 263 events
  from 3 coordinators + 2 clients + the driver. Leader process is killed with
  `SIGKILL` only after the holder is observed inside its CS.
* [Full regression output](test-results.txt): 38/38 passed. The same real failure
  integration was also repeated three additional times successfully. No mocked
  recovery output is included in these samples.

Selected events copied from the actual ordered failure capture (Lamport time):

| Time | Node | Event |
|---|---|---|
| 74 | failure-holder | CS_ENTER |
| 78 | failure-driver | LEADER_KILL_REQUESTED |
| 122 | standin-2 | LEADER_FAILURE_DETECTED |
| 123 | standin-2 | LEADER_ELECTED |
| 124 | standin-2 | LOCK_STATE_RESTORED |
| 150 | standin-2 | LOCK_DENIED |
| 156 | failure-driver | CONTENDER_BLOCKED_AFTER_FAILOVER |
| 159 | failure-holder | CS_EXIT |
| 169 | standin-2 | LOCK_RELEASED |
| 179 | standin-2 | LOCK_GRANTED |
| 182 | failure-contender | CS_ENTER |
| 184 | failure-contender | CS_EXIT |
| 194 | standin-2 | LOCK_RELEASED |

The exact logical numbers and ephemeral ports can differ between runs. Both raw
sample directories re-merge byte-for-byte into their committed `ordered.jsonl`.

## Replace the stand-in when Josiah's code lands

Implement the `RecoveryAdapter` Protocol in `src.communication.failure_test` and
provide a zero-argument factory:

```bash
python3 -m src.communication.failure_test \
  --adapter src.coordination.josiah_adapter:create_adapter \
  --output logs/milestone4-final-protocol
```

Required hooks: start isolated nodes with the capture environment; observe the
leader; start and observe a real held CS; kill/wait the owned leader; observe a
replacement; wait for **safe** lock reset/restore; exercise old holder + contenders
and return actual intervals; stop/join owned processes. Preserve the holder/fencing
safety invariant, logical timestamps, and assertion checks. Integrate Andrew's real
protected resource inside those granted CSs instead of the stand-in ledger.
The harness/merger need no protocol changes. Re-run it and capture new real evidence;
do not relabel the stand-in's trace as output from the final team implementation.
