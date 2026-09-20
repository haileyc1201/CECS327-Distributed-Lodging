# Source Code

Milestone 1 services and clients:

| Folder | Role | Port |
|--------|------|------|
| `property-service/` | Property lookup / list (TCP JSON) | 5001 |
| `reservation-service/` | Availability check + booking (TCP JSON) | 5002 |
| `payment-service/` | Mock payment approval (TCP JSON) | 5003 |
| `gateway/` | Flask HTTP API for the React UI | 8000 |
| `client/` | Simple TCP demo client | — |

The React UI lives in `/frontend` at the repo root.

Start commands are documented in the root README.
