#!/bin/bash
set -euo pipefail
ROOT="$HOME/Downloads/CECS327-Distributed-Lodging"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

# kill leftovers from a previous run
for p in 5001 5002 5003 8000 5173; do
  lsof -ti tcp:$p | xargs kill -9 2>/dev/null || true
done

mkdir -p logs
python src/property-service/property_service.py >logs/property.out 2>&1 &
python src/payment-service/payment_service.py >logs/payment.out 2>&1 &
python src/reservation-service/reservation_service.py >logs/reservation.out 2>&1 &
python src/gateway/gateway.py >logs/gateway.out 2>&1 &
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5173) >logs/frontend.out 2>&1 &

sleep 2
echo "Lodging demo running:"
echo "  UI:      http://127.0.0.1:5173"
echo "  API:     http://127.0.0.1:8000/api/health"
echo "  Logs:    $ROOT/logs"
echo "Stop with: kill \$(lsof -ti tcp:5001,5002,5003,8000,5173)"
open "http://127.0.0.1:5173" 2>/dev/null || true
