# CECS 327 Distributed Lodging: Milestone 2, Communication

CECS 327, Section 02, California State University, Long Beach

Team: Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter and Anthony Torres

We are building a distributed lodging reservation system, similar to Airbnb. This branch, `main`, holds the Python simulation. Every node runs as its own OS process and the nodes talk over TCP sockets. The live web version of the same protocol, with Node microservices, a React UI and Cloudflare Workers with D1, is on [`tom-react-frontend`](https://github.com/haileyc1201/CECS327-Distributed-Lodging/tree/tom-react-frontend) and runs at https://pitchblack.icu.

## What Milestone 2 Delivers

| Requirement | How we did it | Code |
|---|---|---|
| Marshalling and unmarshalling | A message envelope `{id, type, sender, receiver, timestamp, correlation_id, payload}` converted to JSON bytes or typed XML and back, with the before and after state logged | `src/communication/codec.py`, `transport.py` |
| Sockets and RPC | JSON-RPC 2.0 over TCP sockets with length-prefixed frames `[len][J/X][body]` | `src/communication/rpc.py`, `server.py`, `transport.py` |
| Request-reply | `availability.check`, `property.get` and `reservation.book`, where Reservation calls Property | `src/communication/services.py` |
| Publish-subscribe with multiple subscribers | A broker delivers `booking.created` to the notification, analytics and audit services | `src/communication/broker.py` |
| Group communication | A coordinator and 3 property replicas with join, leave, `group.view`, numbered multicast with acks, and failure detection | `src/communication/group.py` |
| Timestamped logging | Every SEND and RECV goes to `logs/messages.jsonl` as ISO-8601 JSON Lines and to stdout | `src/communication/msglog.py` |
| Demo and tests | One script starts every node and runs each mechanism; 10 unit and integration tests | `src/communication/demo.py`, `tests/test_communication.py` |

### Nodes and Ports

| Node | Port |
|---|---|
| property-rpc | 6001 |
| reservation-rpc | 6002 |
| broker | 6010 |
| group-coordinator | 6020 |
| replica-1, replica-2, replica-3 | 6101, 6102, 6103 |
| notification, analytics and audit services | subscribers that connect to the broker |

## Required Software

- Python 3.10 or newer. We only use the standard library.
- Git

## Install Dependencies

There are no third-party packages, so cloning is enough:

```bash
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging
python3 --version   # 3.10+
```

## Start Each Service

From the repository root, run each command in its own terminal:

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

The demo does the following:

1. Starts all 10 nodes as separate processes.
2. Shows the JSON and XML marshalling round trip.
3. Runs RPC request-reply with both JSON and XML on the wire.
4. Books property 101. The booking calls Property, publishes to 3 subscribers and multicasts to 3 replicas.
5. Shows a double booking being rejected.
6. Kills replica-3, so the next multicast detects the failure and the group view shrinks.
7. Prints a summary from `logs/messages.jsonl`.

## Reproduce the Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

| # | What it checks |
|---|---|
| TC1 | JSON and XML round trips keep types, and the envelope timestamp is ISO-8601 |
| TC2 | Request-reply for `availability.check` and `property.get` in JSON and XML, plus 404 and -32601 errors |
| TC3 | A booking reaches all 3 subscribers and all 3 replicas apply the multicast; a double booking is rejected |
| TC4 | Group join, view and multicast; a failed member is removed and leave updates the view |
| TC5 | Pub-sub only delivers to the matching topic |
| TC6 | Every log entry is ISO-8601 and SEND entries hold the message before and after marshalling |

| Suite | Result |
|---|---|
| Python, this branch | 10/10 pass (`docs/logs/python-test-results.txt`) |
| Node, `tom-react-frontend` | 7/7 pass |
| Cloudflare Worker, live | 20/20 pass |

## Screenshots

All screenshots come from real runs and live in [`docs/milestone-2/screenshots/`](docs/milestone-2/screenshots).

| # | Screenshot |
|---|---|
| 01 | [Python demo, full run with 10 processes](docs/milestone-2/screenshots/01_python_demo_full_run.png) |
| 02 | [Request-reply with JSON-RPC over TCP](docs/milestone-2/screenshots/02_request_reply_jsonrpc_tcp.png) |
| 03 | [Marshalling before and after, JSON and XML](docs/milestone-2/screenshots/03_marshalling_before_after.png) |
| 04 | [Pub-sub: booking.created reaching 3 subscribers](docs/milestone-2/screenshots/04_pubsub_three_subscribers.png) |
| 05 | [Group communication: multicast, acks, membership and failure](docs/milestone-2/screenshots/05_group_multicast_membership.png) |
| 06 | [Timestamped messages.jsonl](docs/milestone-2/screenshots/06_timestamped_message_log.png) |
| 07 | [Python tests, 10/10](docs/milestone-2/screenshots/07_python_tests_passing.png) |
| 08 | [Node comm demo](docs/milestone-2/screenshots/08_node_comm_demo.png) |
| 09 | [Node tests, 7/7](docs/milestone-2/screenshots/09_node_tests_passing.png) |
| 10a | [Worker under wrangler dev, 20/20 checks](docs/milestone-2/screenshots/10a_worker_local_tests.png) |
| 10b | [Worker GET /api/comm/logs output](docs/milestone-2/screenshots/10b_worker_comm_logs_json.png) |
| 11 | [React UI on the local stack after a booking through /api/rpc](docs/milestone-2/screenshots/11_react_ui.png) |
| 12 | [Live Worker at lodging.pitchblack.icu, 20/20 checks](docs/milestone-2/screenshots/12_live_worker_tests.png) |
| 13 | [Live GET /api/comm/logs output](docs/milestone-2/screenshots/13_live_worker_comm_logs.png) |

## Report and Logs

- Report: [`CECS327_Milestone2_Communication_Report.pdf`](docs/milestone-2/CECS327_Milestone2_Communication_Report.pdf), with its [markdown source](docs/milestone-2/CECS327_Milestone2_Communication_Report.md). It covers the communication model, message formats, marshalling, why we chose sockets and RPC, the pub-sub and group designs, a side-by-side look at the Python and Cloudflare versions, and real log excerpts.
- Logs from real runs are in [`docs/logs/`](docs/logs):
  - `python-messages.jsonl`, `python-demo-output.txt`, `python-test-results.txt` for the Python simulation on `main`
  - `node-messages.jsonl`, `node-demo-output.txt`, `node-test-results.txt` for the Node stack on `tom-react-frontend`
  - `worker-local-messages.jsonl`, `worker-local-demo-output.txt` for the Cloudflare Worker under `wrangler dev`
- At runtime, messages are written to `logs/messages.jsonl`, which git ignores.
- There is no video for this milestone.


## Milestone 1

Milestone 1, due September 24, 2026, built our first three socket services. They are still in the repo, unchanged:

- `src/property-service/property_service.py` on port 5001
- `src/reservation-service/reservation_service.py` on port 5002
- `src/payment-service/payment_service.py` on port 5003
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
git add . && git commit -m "Describe what you changed"
git push -u origin yourname-task   # then open a pull request
```
