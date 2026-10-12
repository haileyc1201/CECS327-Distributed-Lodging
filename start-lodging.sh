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
for p in 5001 5002 5003 5010 5101 5102 5103 5201 5202 5203 8000 5173; do
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:$p | xargs -r kill -9 2>/dev/null || true
  fi
done

mkdir -p logs
node services/property-service/server.js >logs/property.out 2>&1 &
node services/payment-service/server.js >logs/payment.out 2>&1 &
node services/comm-hub/server.js >logs/hub.out 2>&1 &
# brief pause so property/payment are up before reservation
sleep 0.5
node services/reservation-service/server.js >logs/reservation.out 2>&1 &
node services/gateway/server.js >logs/gateway.out 2>&1 &
# communication milestone: 3 pub-sub subscribers + 3 group members
i=0; for n in notification-service analytics-service audit-service; do
  node services/comm-hub/node.js subscriber $n $((5101+i)) booking.created >logs/$n.out 2>&1 &
  i=$((i+1)); done
for i in 1 2 3; do
  node services/comm-hub/node.js member replica-$i $((5200+i)) property-replicas >logs/replica-$i.out 2>&1 &
done
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5173) >logs/frontend.out 2>&1 &

sleep 2
echo "Lodging demo running:"
echo "  UI:      http://127.0.0.1:5173"
echo "  API:     http://127.0.0.1:8000/api/health"
echo "  RPC:     POST http://127.0.0.1:8000/api/rpc   (JSON-RPC 2.0 envelope)"
echo "  MsgLog:  http://127.0.0.1:8000/api/comm/logs"
echo "  Logs:    $ROOT/logs"
echo "Stop with: kill \$(lsof -ti tcp:5001,5002,5003,5010,5101,5102,5103,5201,5202,5203,8000,5173) 2>/dev/null"
