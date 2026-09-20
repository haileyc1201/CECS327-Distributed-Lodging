# CECS 327 Distributed Lodging

Milestone 1 project for CECS 327, Section 02 at California State University, Long Beach.

**Team:** Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter, and Anthony Torres

**Milestone 1 due:** September 24, 2026

## Project

We are building a distributed lodging reservation system similar to Airbnb. Guests will be able to search properties and make reservations, while hosts will be able to create listings and manage availability.

For Milestone 1, we have three backend TCP services plus an HTTP gateway and React UI:

- Property Service (TCP `:5001`)
- Reservation Service (TCP `:5002`)
- Payment Service (TCP `:5003`)
- HTTP Gateway (Flask `:8000`) — bridges browsers to the TCP services
- React frontend (Vite `:5173`)

```text
React UI / Client
  -> HTTP Gateway (:8000)
       -> Property Service (:5001)
       -> Reservation Service (:5002)
            -> Property Service
            -> Payment Service (:5003)
            -> data/reservations.csv + data/properties.csv
```

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
├── src/
│   ├── client/               # TCP demo client
│   ├── gateway/              # Flask HTTP API bridge
│   ├── property-service/
│   ├── reservation-service/
│   └── payment-service/
├── data/
│   ├── properties.csv
│   └── reservations.csv
├── logs/
├── screenshots/
└── README.md
```

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- One-time setup:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install flask flask-cors

cd frontend && npm install && cd ..
```

## How to Run (Milestone 1 Demo)

Open **five terminals** from the repo root (or run services in the background).

### 1. Property Service

```bash
source .venv/bin/activate
python src/property-service/property_service.py
```

### 2. Payment Service

```bash
source .venv/bin/activate
python src/payment-service/payment_service.py
```

### 3. Reservation Service

```bash
source .venv/bin/activate
python src/reservation-service/reservation_service.py
```

### 4. HTTP Gateway

```bash
source .venv/bin/activate
python src/gateway/gateway.py
```

### 5. React Frontend

```bash
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173**

## Demo Steps (for video)

1. Start Property, Payment, Reservation, Gateway, then Frontend (order above).
2. In the browser, confirm ~12 property **cards** load (city, beds, price, available badge). Search/filter works client-side.
3. Enter a guest name, click a card, then **Book** (e.g. property 101).
4. Confirm the result shows `accepted`, a reservation id, and payment `approved`.
5. Refresh — that property should now be unavailable. Cancel from **Your reservations** to refund and unlock.
6. **Hard reset** (header button, two confirms) restores seed CSV data for another run. Or: `curl -X POST http://127.0.0.1:8000/api/reset`
7. Optional: use the TCP client:

```bash
source .venv/bin/activate
python src/client/client.py list
python src/client/client.py book 103 Alice
```

8. Optional curl checks:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/properties
curl -X POST http://127.0.0.1:8000/api/reservations \
  -H 'Content-Type: application/json' \
  -d '{"property_id": 103, "guest_name": "Tom"}'
curl -X POST http://127.0.0.1:8000/api/reset
```

Data files are CSV (`data/properties.csv`, `data/reservations.csv`), not JSON.

## GitHub Pages (static UI demo)

Teammates can try the React UI without running Python. Pages serves a **demo/mock mode** (in-browser store seeded with the same ~12 listings). Banner shows when mock is active. Book / cancel / Hard reset work client-side only.

- Workflow: `.github/workflows/pages.yml` builds `frontend/` with `base: /CECS327-Distributed-Lodging/` and deploys on push to `main` or `tom-react-frontend`.
- Enable **Settings → Pages → Source: GitHub Actions** on the team repo.
- Expected URL: https://haileyc1201.github.io/CECS327-Distributed-Lodging/
- Real distributed TCP demo still requires running Property, Payment, Reservation, and Gateway locally.

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
