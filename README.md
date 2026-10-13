# CECS 327 Distributed Lodging: Milestone 2, Communication

CECS 327, Section 02, California State University, Long Beach

Team: Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter and Anthony Torres

We are building a distributed lodging reservation system, similar to Airbnb. This branch, `tom-react-frontend`, is the live web version. Locally it runs as Node.js HTTP microservices with a React UI. When hosted, it runs on a Cloudflare Worker with D1 and a Durable Object. The Python socket simulation of the same protocol is on [`main`](https://github.com/haileyc1201/CECS327-Distributed-Lodging/tree/main).

Live site: https://pitchblack.icu

## What Milestone 2 Delivers

| Requirement | Local Node stack | Cloudflare Worker |
|---|---|---|
| Marshalling and unmarshalling | The envelope is converted to JSON or typed XML and back, picked by `Content-Type`, with before and after logged. `services/shared/messaging.js` | Same format. `cloudflare/src/comm/marshal.ts` |
| RPC | JSON-RPC 2.0 over HTTP: `POST :8000/api/rpc`, forwarded to the Comm Hub `/rpc`. `services/comm-hub/server.js` | `POST /api/rpc`. `cloudflare/src/comm/routes.ts` |
| Request-reply | `availability.check`, `property.get` and `reservation.book`, where Reservation calls Property and then Payment | Same methods, backed by D1 |
| Publish-subscribe with multiple subscribers | `booking.created` goes to 3 subscriber processes. `services/comm-hub/node.js` | The `CommHub` Durable Object delivers to 3 built-in subscribers and to WebSocket subscribers at `/api/comm/ws?role=subscriber`. `cloudflare/src/comm/hub.ts` |
| Group communication | Group `property-replicas` with 3 replica processes: join, leave, view, numbered multicast with acks, and failure detection | The Durable Object coordinates mailbox members through `/api/group/*` with a heartbeat lease, plus WebSocket members at `/api/comm/ws?role=member` |
| Timestamped logging | Every SEND and RECV goes to `logs/messages.jsonl`, readable at `GET /api/comm/logs` | D1 table `message_log`, readable at `GET /api/comm/logs?limit=&node=`. `cloudflare/src/comm/msglog.ts` |
| Demo and tests | `scripts/comm-demo.js`, `tests/comm.test.js` | `cloudflare/scripts/comm-demo.mjs` with 20 checks |

A booking goes through these steps: the client calls Reservation, Reservation asks Property with `availability.check`, Payment is charged, the booking is saved, `booking.created` is published, an `availability_update` is multicast to `property-replicas`, and the reply lists `notified_subscribers` and `replicas_updated`.

### Local Ports

| Component | Port |
|---|---|
| Property, Reservation, Payment | 5001, 5002, 5003 |
| Comm Hub for RPC, pub-sub and groups | 5010 |
| Subscribers: notification, analytics, audit | 5101, 5102, 5103 |
| Group members: replica-1, replica-2, replica-3 | 5201, 5202, 5203 |
| HTTP Gateway | 8000 |
| React with Vite | 5173 |
| Worker under `wrangler dev` | 8787 |

## Required Software

- Node.js 18 or newer and npm for the local services and tests. We tested on Node 20 and 22.
- Node.js 22 or newer for the Cloudflare Worker with Wrangler 4 and for the hosted test script, which uses the global `WebSocket`.
- A Cloudflare account, only if you want to deploy. Log in with `npx wrangler login` or set `CLOUDFLARE_API_TOKEN`.
- Git

## Install Dependencies

```bash
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging
git checkout tom-react-frontend
npm run install:all              # root + frontend
npm install --prefix cloudflare  # Worker (Node 22+)
```

## Start Each Service

To start everything at once, run `./start-lodging.sh`. It brings up the services, the hub, 3 subscribers, 3 replicas and the UI. To start them one by one, use a terminal for each:

```bash
npm run property      # :5001
npm run payment       # :5003
npm run hub           # :5010
npm run reservation   # :5002
npm run gateway       # :8000
node services/comm-hub/node.js subscriber notification-service 5101 booking.created
node services/comm-hub/node.js subscriber analytics-service    5102 booking.created
node services/comm-hub/node.js subscriber audit-service        5103 booking.created
node services/comm-hub/node.js member replica-1 5201 property-replicas
node services/comm-hub/node.js member replica-2 5202 property-replicas
node services/comm-hub/node.js member replica-3 5203 property-replicas
npm run frontend      # :5173
```

To run the Worker locally:

```bash
npm run cf:build
cd cloudflare
npx wrangler d1 execute cecs327-lodging --local --file=schema.sql   # first time only
npx wrangler dev                                                    # http://127.0.0.1:8787
```

An example RPC call:

```bash
curl -s localhost:8000/api/rpc -H 'content-type: application/json' -d '{"id":"x1","type":"rpc.request","sender":"curl","receiver":null,"timestamp":"2026-10-12T00:00:00.000Z","correlation_id":null,"payload":{"jsonrpc":"2.0","method":"availability.check","params":{"property_id":101},"id":1}}'
```

## Run the Demo

```bash
npm run comm:demo
```

The local demo does the following:

1. Starts all 11 processes.
2. Runs the JSON and XML marshalling round trip.
3. Runs RPC request-reply, including an error case.
4. Books a property, which publishes to 3 subscribers and multicasts to 3 replicas.
5. Shows a double booking being rejected.
6. Kills replica-3 to show failure detection.
7. Prints subscriber and replica state and the output of `/api/comm/logs`.

For the Worker demo:

```bash
BASE_URL=http://127.0.0.1:8787 npm run cf:test           # against wrangler dev
BASE_URL=https://lodging.pitchblack.icu npm run cf:test  # against the deployed Worker
```

### Deployment

We deployed Milestone 2 on October 12, 2026 at about 4:40 PM PT, as Worker version `130a49b4-4b81-41b5-a1e1-cb74e8227111`. It is live at https://lodging.pitchblack.icu and https://pitchblack.icu, and the hosted suite passes 20/20 against the live URL (screenshots 12 and 13).

## Reproduce the Tests

```bash
npm test                                         # Node: node:test, 7 tests
BASE_URL=http://127.0.0.1:8787 npm run cf:test   # Worker: 20 checks
```

| # | What it checks | Node | Worker |
|---|---|---|---|
| TC1 | JSON and XML round trips keep types; ISO-8601 timestamp | ✓ | XML reply checked |
| TC2 | Request-reply for `availability.check` and `property.get` in JSON and XML, plus 404 and -32601 errors | ✓ | ✓ |
| TC3 | A booking notifies every subscriber and multicasts to every replica; a double booking is rejected | ✓ 3 subscribers, 3 replicas | ✓ 3 built-in and 2 WebSocket subscribers; 2 mailbox and 1 WebSocket replica |
| TC4 | Group failure detection, graceful leave and view update | ✓ | ✓ closed WebSocket member is removed |
| TC5 | Pub-sub topic filtering | ✓ | n/a |
| TC6 | Every log entry is ISO-8601, with before and after marshalling, and `/api/comm/logs` works | ✓ | ✓ |

| Suite | Result |
|---|---|
| Node, this branch | 7/7 pass |
| Cloudflare Worker | 20/20 pass under `wrangler dev` and against https://lodging.pitchblack.icu |
| Python, `main` | 10/10 pass |

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

## Milestone 1

In Milestone 1 we built Property, Reservation and Payment as Node HTTP services behind an Express gateway, with a React UI. Data lives in `data/*.csv`, and the original Python TCP services are archived in `archive/python-tcp/`. We also added a Cloudflare Worker and D1 host with the same `/api/*` contract.

The site now runs the Milestone 2 build at:

- https://lodging.pitchblack.icu, also https://pitchblack.icu and https://www.pitchblack.icu
- https://cecs327-lodging.tommalter5.workers.dev

Features include search, booking and cancelling with mock payment and refund, a hard reset through `POST /api/reset`, colorized service logs and a React state panel. The design documents are in `docs/milestone-1/`.

[![Distributed Lodging demo preview](screenshots/demo-preview.png)](https://lodging.pitchblack.icu)

Cloudflare notes:

- The Worker is `cecs327-lodging` and uses the D1 database `cecs327-lodging`. Its config, including the `COMM_HUB` Durable Object, is in `cloudflare/wrangler.toml`.
- Build and deploy with `npm run cf:deploy` on Node 22 or newer.
- Preview locally with `npm run cf:dev`.

## Repository Structure

```text
.
├── services/
│   ├── shared/messaging.js   # M2 envelope, marshalling, logging
│   ├── comm-hub/             # M2 RPC + pub-sub + group hub, subscriber/member nodes
│   ├── property-service/  reservation-service/  payment-service/  gateway/
├── cloudflare/
│   ├── src/comm/             # M2 marshal, msglog (D1), CommHub DO, routes
│   ├── src/services/         # property / payment / reservation modules
│   ├── scripts/comm-demo.mjs
│   ├── wrangler.toml  schema.sql
├── frontend/                 # React + Vite UI
├── scripts/                  # comm-demo.js, comm-cluster.js
├── tests/comm.test.js
├── docs/milestone-1/  docs/milestone-2/  docs/logs/
├── archive/python-tcp/
├── data/  logs/  screenshots/
├── package.json  start-lodging.sh
```

## Working on the Project

```bash
git pull
git checkout -b yourname-task
git add . && git commit -m "Describe what you changed"
git push -u origin yourname-task   # then open a pull request
```
