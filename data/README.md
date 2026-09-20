# Data

- `properties.json` — shared property listings (availability updated on booking/cancel)
- `reservations.json` — reservations; status is `confirmed` or `cancelled`

Cancel restores property availability and records a mock payment refund.

For a clean demo, set properties back to `available: true` and reset `reservations.json` to `[]`.
