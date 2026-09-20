# Frontend (React + Vite)

Browser UI for the Milestone 1 lodging demo. Talks to the HTTP gateway at `http://127.0.0.1:8000` (proxied in dev).

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

Optional: set `VITE_API_URL=http://127.0.0.1:8000` if not using the Vite proxy.

## Scripts

- `npm run dev` — start Vite dev server
- `npm run build` — production build
- `npm run preview` — preview production build
