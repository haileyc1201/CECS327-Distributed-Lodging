# HTTP Gateway

Flask API on `127.0.0.1:8000` that proxies HTTP requests to the TCP microservices so the browser/React app can use them.

## Run

```bash
# from repo root
source .venv/bin/activate
pip install flask flask-cors   # once
python src/gateway/gateway.py
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/properties` | List all properties |
| GET | `/api/properties/<id>` | Get one property |
| POST | `/api/reservations` | Book `{ property_id, guest_name }` |
| GET | `/api/logs` | Recent lines from `logs/*.log` |
