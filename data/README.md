# Data

CSV files used by the Property and Reservation services (stdlib `csv` only).

- `properties.csv` — columns: `id,name,price,available,city,beds`
- `reservations.csv` — columns: `reservation_id,property_id,property_name,guest_name,amount,payment_id,refund_id,status,created_at,cancelled_at`

An empty reservations file still has a header row.

## Reset demo data

**Preferred:** use the UI **Hard reset** button (two confirms) or:

```bash
curl -X POST http://127.0.0.1:8000/api/reset
```

That restores seed listings (102, 107, 112 unavailable; others available) and clears reservations to header-only.

Manual reset: copy seed availability into `properties.csv` and keep only the header in `reservations.csv`.
