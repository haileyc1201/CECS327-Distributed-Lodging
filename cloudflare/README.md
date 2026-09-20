# Cloudflare Worker — `cecs327-lodging`

Hosted demo: Hono Worker serves the React UI (Workers Assets) and the same `/api/*` contract as the local Express gateway. Data lives in D1 (`cecs327-lodging`).

## Modules (distributed-in-code)

| Module | Role |
|--------|------|
| `src/services/propertyService.ts` | D1 property list / get / availability |
| `src/services/paymentService.ts` | Mock approve + refund |
| `src/services/reservationService.ts` | Book / cancel orchestration |
| `src/index.ts` | Hono gateway routes + static assets |

## Prerequisites

- **Node.js 22+** (Wrangler 4 requires it)
- Cloudflare account with D1 database `cecs327-lodging` already created

## One-time setup

```bash
# From repo root
cd frontend && VITE_DEPLOY_TARGET=cloudflare npm install && VITE_DEPLOY_TARGET=cloudflare npm run build && cd ..
cd cloudflare && npm install
```

D1 database id is already in `wrangler.toml`. Schema/seed: `schema.sql` (tables + 12 properties already applied in Tom's account).

## Deploy

Requires `CLOUDFLARE_API_TOKEN` (or `wrangler login`):

```bash
cd frontend && VITE_DEPLOY_TARGET=cloudflare npm run build && cd ../cloudflare
npx wrangler deploy
```

After deploy, open the `*.workers.dev` URL. Same-origin `/api/health` disables the browser mock.

## Local preview

```bash
cd frontend && VITE_DEPLOY_TARGET=cloudflare npm run build && cd ../cloudflare
npx wrangler dev
```

## Hard reset

`POST /api/reset` restores seed availability (102, 107, 112 unavailable) and deletes all reservations. The UI still requires two confirms.
