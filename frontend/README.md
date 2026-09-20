# Frontend (React + Vite)

Browser UI for the Milestone 1 lodging skeleton demo. Talks to the HTTP gateway at `http://127.0.0.1:8000` (proxied in dev), or runs in **demo/mock mode** on GitHub Pages.

## Features

- Search (name, city, id) and filters (available only, min beds)
- Clickable property cards with detail modal + Book
- Reservations list with Cancel (refund path)
- Hard reset (two confirms) to restore seed data
- Collapsible activity logs

## Setup

```bash
cd frontend
npm install
```

## Run (dev)

Start the three TCP services and the gateway first, then:

```bash
npm run dev
```

Open http://127.0.0.1:5173

Force mock data locally: `VITE_DEMO_MODE=true npm run dev`

## Scripts

- `npm run dev` — Vite dev server
- `npm run build` — production build (`base` set for GitHub Pages)
- `npm run preview` — preview production build
