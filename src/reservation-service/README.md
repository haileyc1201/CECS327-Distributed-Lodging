# Reservation Service

Reservation requests over TCP JSON on `127.0.0.1:5002`.

Calls Property Service (`:5001`) and Payment Service (`:5003`).

## Run

```bash
python src/reservation-service/reservation_service.py
```

## Actions

- `check_availability` — verify property exists and is available
- `book` / `create_reservation` — check property → process payment → persist reservation → mark property unavailable

Persists to `data/reservations.json` and updates `data/properties.json`.
