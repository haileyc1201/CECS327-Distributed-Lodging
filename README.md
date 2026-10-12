# CECS 327 Distributed Lodging

Milestone 1 project for CECS 327, Section 02 at California State University, Long Beach.

**Team:** Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter, and Anthony Torres

**Milestone 1 due:** September 24, 2026

## Project

We are building a distributed lodging reservation system similar to Airbnb. Guests will be able to search properties and make reservations, while hosts will be able to create listings and manage availability.

For Milestone 1, we are starting with three backend services:

- Property Service
- Reservation Service
- Payment Service

The client starts the request. The basic flow for this milestone is:

```text
Client
  -> Property Service
  -> Reservation Service
  -> Payment Service
  -> Reservation result
```

We also use shared persistent storage for important data such as properties and reservations.

User Service and Review Service are planned for later milestones.

## Repository Structure

```text
.
├── docs/
│   ├── diagrams/
│   └── milestone-1/
│       ├── 01-system-overview.md
│       ├── 02-architecture.md
│       ├── 03-components.md
│       ├── 04-system-model.md
│       └── 05-communication-flow.md
├── src/
│   ├── client/
│   ├── property-service/
│   ├── reservation-service/
│   ├── payment-service/
│   └── communication/   # milestone 2 comm layer
├── tests/
├── data/
├── logs/
├── screenshots/
└── README.md
```

## Milestone 1 Goal

The Milestone 1 prototype needs at least three communicating processes or services, a simple client request, a server response, and logs showing the messages exchanged.

## Communication Milestone (Python simulation)

This branch is the **Python simulation**. The live Node/React/Cloudflare version of the same protocol is on [`tom-react-frontend`](https://github.com/haileyc1201/CECS327-Distributed-Lodging/tree/tom-react-frontend).
The full report is in [`docs/communication-milestone/CECS327_Communication_Milestone_Report.pdf`](docs/communication-milestone/CECS327_Communication_Milestone_Report.pdf) ([markdown](docs/communication-milestone/CECS327_Communication_Milestone_Report.md)). Real run logs are in [`docs/logs/`](docs/logs).

| Requirement | Where |
|---|---|
| Marshalling / unmarshalling (JSON + typed XML), before/after logged | `src/communication/codec.py`, `transport.py`, `msglog.py` |
| Sockets + RPC | JSON-RPC 2.0 over TCP sockets with length-prefixed frames (`rpc.py`) |
| Request-reply | `availability.check`, `property.get`, `reservation.book` (Reservation → Property) |
| Publish-subscribe, multiple subscribers | `broker.py`: `booking.created` → notification, analytics, audit services |
| Group communication + membership | `group.py`: group `property-replicas`, join/leave/view, numbered multicast with acks, failure detection |
| ISO-8601 logging of every send/receive | `logs/messages.jsonl` (+ stdout) |

Ports: property-rpc 6001, reservation-rpc 6002, broker 6010, group-coordinator 6020, replicas 6101-6103. Hailey's Milestone 1 services (5001/5002/5003) and `src/client/client.py` are unchanged and still work.

### Required software

- Python 3.10+ (standard library only, nothing to `pip install`)

### Install dependencies

None. Clone the repo and run from the repository root.

### Start each service (one terminal each, from the repo root)

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

### Run the demo

```bash
python3 -m src.communication.demo
```

This starts all 10 nodes as separate processes. It then shows the JSON/XML marshalling round-trip, RPC request-reply (JSON and XML on the wire), a booking that triggers pub-sub to 3 subscribers and a multicast to 3 replicas, and a rejected double booking. It kills replica-3 to show failure detection and prints a summary of `logs/messages.jsonl`.

Original Milestone 1 flow (unchanged):

```bash
python3 src/property-service/property_service.py &
python3 src/reservation-service/reservation_service.py &
python3 src/client/client.py
```

### Reproduce the test cases

```bash
python3 -m unittest discover -s tests -t . -v
```

| # | Test case |
|---|---|
| TC1 | JSON and XML round-trip keeps types; ISO-8601 envelope timestamp |
| TC2 | Request-reply `availability.check` / `property.get` (JSON and XML); 404 and -32601 errors |
| TC3 | Booking → 3 subscribers get `booking.created`, 3 replicas apply the update, double booking rejected |
| TC4 | Group join/view/multicast, failed member removed, leave |
| TC5 | Pub-sub delivers only to matching topic |
| TC6 | Every log entry ISO-8601; SEND entries carry before/after marshalling |

### Contribution table

| Member | Contribution |
|---|---|
| _Member 1_ | _TBD_ |
| _Member 2_ | _TBD_ |
| _Member 3_ | _TBD_ |
| _Member 4_ | _TBD_ |
| _Member 5_ | _TBD_ |
| _Member 6_ | _TBD_ |
| _Member 7_ | _TBD_ |

## Clone the Repository

```bash
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging
```

## Working on the Project

Before starting work:

```bash
git pull
git checkout -b yourname-task
```

After making changes:

```bash
git add .
git commit -m "Describe what you changed"
git push -u origin yourname-task
```

Then open a pull request on GitHub so the change can be merged into `main`.
