# Client

TCP demo client for Milestone 1. The primary UI is the React frontend under `/frontend`.

## Run

Requires Property and Reservation services (and Payment if booking).

```bash
python src/client/client.py              # check availability for 101
python src/client/client.py list         # list properties
python src/client/client.py book 101 Tom # book property 101
```
