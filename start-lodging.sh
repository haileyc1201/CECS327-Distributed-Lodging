#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d node_modules ]]; then
  npm install
fi
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

# kill leftovers from a previous run
for p in 5001 5002 5003 8000 5173; do
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:$p | xargs -r kill -9 2>/dev/null || true
  fi
done

mkdir -p logs
node services/property-service/server.js >logs/property.out 2>&1 &
node services/payment-service/server.js >logs/payment.out 2>&1 &
# brief pause so property/payment are up before reservation
sleep 0.5
node services/reservation-service/server.js >logs/reservation.out 2>&1 &
node services/gateway/server.js >logs/gateway.out 2>&1 &
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5173) >logs/frontend.out 2>&1 &

sleep 2
echo "Lodging demo running:"
echo "  UI:      http://127.0.0.1:5173"
echo "  API:     http://127.0.0.1:8000/api/health"
echo "  Logs:    $ROOT/logs"
echo "Stop with: kill \$(lsof -ti tcp:5001,5002,5003,8000,5173) 2>/dev/null"
