# CECS 327 Distributed Lodging, Milestone 2: Communication

CECS 327, Section 02, California State University, Long Beach.

**Team:** Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter, and Anthony Torres

A distributed lodging reservation system similar to Airbnb. This branch (`main`) is the **Python simulation**: every node is a separate OS process, and nodes communicate over TCP sockets. The live web version of the same protocol (Node microservices, React UI, Cloudflare Workers + D1) is on [`tom-react-frontend`](https://github.com/haileyc1201/CECS327-Distributed-Lodging/tree/tom-react-frontend).

## What Milestone 2 Delivers

| Requirement | How | Where in the code |
|---|---|---|
| Marshalling / unmarshalling | Message envelope `{id, type, sender, receiver, timestamp, correlation_id, payload}` ↔ JSON bytes or typed XML; before/after state logged | `src/communication/codec.py`, `transport.py` |
| Sockets + RPC | JSON-RPC 2.0 over TCP sockets with length-prefixed frames (`[len][J/X][body]`) | `src/communication/rpc.py`, `server.py`, `transport.py` |
| Request-reply | `availability.check`, `property.get`, `reservation.book` (Reservation → Property) | `src/communication/services.py` |
| Publish-subscribe (multiple subscribers) | Broker; `booking.created` → notification, analytics and audit services | `src/communication/broker.py` |
| Group communication (membership) | Coordinator + 3 property replicas: join/leave, `group.view`, numbered multicast with acks, failure detection | `src/communication/group.py` |
| Timestamped logging | Every SEND/RECV as ISO-8601 JSON Lines in `logs/messages.jsonl` + stdout | `src/communication/msglog.py` |
| Demo + tests | Starts all nodes as processes and runs every mechanism; 10 unit/integration tests | `src/communication/demo.py`, `tests/test_communication.py` |

### Nodes and ports

| Node | Port |
|---|---|
| property-rpc | 6001 |
| reservation-rpc | 6002 |
| broker (pub-sub) | 6010 |
| group-coordinator | 6020 |
| replica-1 / -2 / -3 | 6101 / 6102 / 6103 |
| notification-, analytics-, audit-service | subscribers (connect to broker) |

## Required Software

- Python 3.10 or newer (standard library only)
- Git

## Install Dependencies

There are no third-party packages to install:

```bash
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging
python3 --version   # 3.10+
```

## Start Each Service

Run each command in its own terminal, from the repository root:

```bash
python3 -m src.communication.run property
python3 -m src.communication.run broker
python3 -m src.communication.run coordinator
python3 -m src.communication.run reservation
python3 -m src.communication.run subscriber notification-service
python3 -m src.communication.run subscriber analytics-service
python3 -m src.communication.run subscriber audit-service
python3 -m src.communication.run replica replica-1 6101
python3 -m src.communication.run replica replica-2 6102
python3 -m src.communication.run replica replica-3 6103
```

## Run the Demo

```bash
python3 -m src.communication.demo
```

The demo:

1. Starts all 10 nodes as separate processes.
2. Shows the JSON and XML marshalling round-trip.
3. Runs RPC request-reply, with JSON and XML on the wire.
4. Books property 101. The booking calls Property, publishes to 3 subscribers and multicasts to 3 replicas.
5. Shows a double booking being rejected.
6. Kills replica-3. The next multicast detects the failure and the group view shrinks.
7. Prints a summary from `logs/messages.jsonl`.

## Test Cases

```bash
python3 -m unittest discover -s tests -t . -v
```

| # | Test case |
|---|---|
| TC1 | JSON and XML marshal/unmarshal round-trip keeps types; ISO-8601 envelope timestamp |
| TC2 | Request-reply `availability.check` / `property.get` in JSON and XML; 404 and -32601 errors |
| TC3 | Booking → 3 subscribers receive `booking.created`, 3 replicas apply the multicast; double booking rejected |
| TC4 | Group join/view/multicast; a failed member is removed; leave updates the view |
| TC5 | Pub-sub delivers only to the matching topic |
| TC6 | Every log entry is ISO-8601; SEND entries carry the message before and after marshalling |

Latest result: `Ran 10 tests ... OK` (see `docs/logs/python-test-results.txt`).

## Report and Logs

- **Report (PDF):** [`docs/milestone-2/CECS327_Milestone2_Communication_Report.pdf`](docs/milestone-2/CECS327_Milestone2_Communication_Report.pdf) ([markdown source](docs/milestone-2/CECS327_Milestone2_Communication_Report.md)). It covers the communication model, message formats, marshalling, why sockets/RPC, the pub-sub and group designs, a side-by-side comparison of the Python and web/Cloudflare paths, and real log excerpts.
- **Logs from real runs:** [`docs/logs/`](docs/logs)
  - `python-messages.jsonl`, `python-demo-output.txt`, `python-test-results.txt`: Python simulation (`main`)
  - `node-messages.jsonl`, `node-demo-output.txt`, `node-test-results.txt`: Node stack (`tom-react-frontend`)
  - `worker-local-messages.jsonl`, `worker-local-demo-output.txt`: Cloudflare Worker under `wrangler dev`
- Runtime logs are written to `logs/messages.jsonl` (git-ignored).
- No video for this milestone.

## Screenshots

These are from real runs; all files are in [`docs/milestone-2/screenshots/`](docs/milestone-2/screenshots).

| # | Screenshot |
|---|---|
| 01 | [Python demo, full run (10 processes)](docs/milestone-2/screenshots/01_python_demo_full_run.png) |
| 02 | [Request-reply: JSON-RPC over TCP](docs/milestone-2/screenshots/02_request_reply_jsonrpc_tcp.png) |
| 03 | [Marshalling before/after (JSON + XML)](docs/milestone-2/screenshots/03_marshalling_before_after.png) |
| 04 | [Pub-sub: booking.created to 3 subscribers](docs/milestone-2/screenshots/04_pubsub_three_subscribers.png) |
| 05 | [Group communication: multicast, acks, membership, failure](docs/milestone-2/screenshots/05_group_multicast_membership.png) |
| 06 | [ISO-8601 timestamped messages.jsonl](docs/milestone-2/screenshots/06_timestamped_message_log.png) |
| 07 | [Python tests (10/10)](docs/milestone-2/screenshots/07_python_tests_passing.png) |
| 08 | [Node comm demo](docs/milestone-2/screenshots/08_node_comm_demo.png) |
| 09 | [Node tests (7/7)](docs/milestone-2/screenshots/09_node_tests_passing.png) |
| 10a | [Worker under wrangler dev: 20/20 checks](docs/milestone-2/screenshots/10a_worker_local_tests.png) |
| 10b | [Worker GET /api/comm/logs JSON](docs/milestone-2/screenshots/10b_worker_comm_logs_json.png) |
| 11 | [React UI (local stack) after a booking made through /api/rpc](docs/milestone-2/screenshots/11_react_ui.png) |

## Contribution Table

| Member | Milestone 2 contribution |
|---|---|
| _Member 1_ | _TBD_ |
| _Member 2_ | _TBD_ |
| _Member 3_ | _TBD_ |
| _Member 4_ | _TBD_ |
| _Member 5_ | _TBD_ |
| _Member 6_ | _TBD_ |
| _Member 7_ | _TBD_ |

_Fill in names and contributions before submitting._

## Milestone 1 (previous)

Milestone 1 (due September 24, 2026) built the first three socket services. They are still in the repo and unchanged:

- `src/property-service/property_service.py` (:5001)
- `src/reservation-service/reservation_service.py` (:5002)
- `src/payment-service/payment_service.py` (:5003)
- `src/client/client.py`
- `data/properties.json`

```bash
python3 src/property-service/property_service.py &
python3 src/reservation-service/reservation_service.py &
python3 src/client/client.py
```

The design documents are in `docs/milestone-1/`.

## Repository Structure

```text
.
├── docs/
│   ├── milestone-1/
│   ├── milestone-2/          # Milestone 2 report (md + pdf)
│   └── logs/                 # real run logs
├── src/
│   ├── communication/        # Milestone 2 communication layer
│   ├── client/
│   ├── property-service/
│   ├── reservation-service/
│   └── payment-service/
├── tests/
├── data/
├── logs/
└── README.md
```

## Working on the Project

```bash
git pull
git checkout -b yourname-task
# ...changes...
git add . && git commit -m "Describe what you changed"
git push -u origin yourname-task   # then open a pull request
```
