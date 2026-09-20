# Description of Components

| Component | Responsibility |
| --- | --- |
| Guest Client | Searches listings, submits reservation requests, and makes payments |
| Host Client | Creates listings and manages property availability |
| Property/Listing Service | Stores and retrieves property information and availability |
| Reservation Service | Creates reservations and prevents conflicting bookings |
| Payment Service | Simulates processing or approving payment for a reservation |
| Shared Persistent Storage | Stores shared application data such as properties, reservations, and users |

The code folders under `src/` match the three services being implemented for Milestone 1.
