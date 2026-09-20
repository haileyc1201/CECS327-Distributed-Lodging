# Architecture Diagram

For Milestone 1, the first three services are:

- Property Service
- Reservation Service
- Payment Service

The client initiates requests.

The current design is:

```text
Guest Client
    |
    v
Property Service
    |
    v
Reservation Service
    |
    v
Payment Service

Shared Persistent Storage
```

The final architecture diagram should be saved in `docs/diagrams/`.

Later versions of the system are expected to add User Service and Review Service.
