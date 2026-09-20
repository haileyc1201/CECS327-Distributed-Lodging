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
- `cancel` / `cancel_reservation` — refund via Payment Service → mark cancelled → restore availability
- `list` / `list_reservations` — list all reservations

Persists to `data/reservations.csv` and updates `data/properties.csv` (all columns preserved).
