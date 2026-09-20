# CECS 327 Distributed Lodging

Milestone 1 project for CECS 327, Section 02 at California State University, Long Beach.

**Team:** Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter, and Anthony Torres

**Milestone 1 due:** September 24, 2026

## Project

We are building a distributed lodging reservation system similar to Airbnb. Guests will be able to search properties and make reservations, while hosts will be able to create listings and manage availability.

For Milestone 1, we have three backend **Node.js HTTP** microservices plus an Express gateway and React UI:

- Property Service (HTTP `:5001`)
- Reservation Service (HTTP `:5002`)
- Payment Service (HTTP `:5003`)
- HTTP Gateway (Express `:8000`) — single API surface for the React UI
- React frontend (Vite `:5173`)

```text
React UI (:5173)
  -> Gateway Express (:8000)
       -> Property Service (:5001)
       -> Reservation Service (:5002)
            -> Property Service (HTTP)
            -> Payment Service (:5003)
            -> data/reservations.csv + data/properties.csv
```

> **Note:** The original Python TCP services are archived under `archive/python-tcp/`.
> Node.js HTTP is the current stack.

User Service and Review Service are planned for later milestones.

## Ports

| Component            | Port |
|----------------------|------|
| Property Service     | 5001 |
| Reservation Service  | 5002 |
| Payment Service      | 5003 |
| HTTP Gateway         | 8000 |
| React (Vite)         | 5173 |

## Repository Structure

```text
.
├── docs/
├── frontend/                 # React + Vite UI
├── services/
│   ├── shared/               # CSV read/write helpers
│   ├── property-service/
│   ├── reservation-service/
│   ├── payment-service/
│   └── gateway/
├── archive/python-tcp/       # Legacy Python TCP + Flask (not primary)
├── data/
│   ├── properties.csv
│   └── reservations.csv
├── logs/
├── screenshots/
├── package.json              # Root Node deps + start scripts
├── start-lodging.sh
└── README.md
```

## Prerequisites

- Node.js 18+ and npm

One-time setup from the repo root:

```bash
npm install
cd frontend && npm install && cd ..
```

Or: `npm run install:all`

## How to Run (Milestone 1 Demo)

### Option A — one command (recommended)

```bash
npm start
```

Starts Property, Payment, Reservation, Gateway, and the Vite frontend together
(via `concurrently`). Open **http://127.0.0.1:5173**

### Option B — shell helper

```bash
./start-lodging.sh
```

### Option C — separate terminals

```bash
# Terminal 1–4 (or one terminal with npm run services)
npm run property      # :5001
npm run payment       # :5003
npm run reservation   # :5002
npm run gateway       # :8000

# Terminal 5
cd frontend && npm run dev
```

Backend-only: `npm run services`

## Demo Steps (for video)

1. Start services + frontend (`npm start` or Option B/C above).
2. In the browser, confirm ~12 property **cards** load (city, beds, price, available badge). Search/filter works client-side.
3. Enter a guest name, click a card, then **Book** (e.g. property 101).
4. Confirm the result shows `accepted`, a reservation id, and payment `approved`.
5. Refresh — that property should now be unavailable. Cancel from **Your reservations** to refund and unlock.
6. **Hard reset** (header button, **two confirms**) restores seed CSV data for another run. Or: `curl -X POST http://127.0.0.1:8000/api/reset`
7. Optional curl checks:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/properties
curl -X POST http://127.0.0.1:8000/api/reservations \
  -H 'Content-Type: application/json' \
  -d '{"property_id": 101, "guest_name": "Tom"}'
curl -X POST http://127.0.0.1:8000/api/reservations/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reservation_id": "res-XXXXXXXX"}'
curl -X POST http://127.0.0.1:8000/api/reset
```

Data files are CSV (`data/properties.csv`, `data/reservations.csv`), not JSON.

## GitHub Pages (static UI demo)

Teammates can try the React UI without running Node services. Pages serves a **demo/mock mode** (in-browser store seeded with the same ~12 listings). Banner shows when mock is active. Book / cancel / Hard reset work client-side only. In local Vite dev, the UI also falls back to mock if the gateway (`:8000`) is down.

- Workflow: `.github/workflows/pages.yml` builds `frontend/` with `base: /CECS327-Distributed-Lodging/` and deploys on push to `main` or `tom-react-frontend`.
- Enable **Settings → Pages → Source: GitHub Actions** on the team repo.
- Expected URL: https://haileyc1201.github.io/CECS327-Distributed-Lodging/
- Real distributed demo still requires running Property, Payment, Reservation, and Gateway locally.

## Milestone 1 Goal

The Milestone 1 prototype needs at least three communicating processes or services, a simple client request, a server response, and logs showing the messages exchanged.

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
