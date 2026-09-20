# CECS 327 Distributed Lodging

Milestone 1 project for CECS 327, Section 02 at California State University, Long Beach.

**Team:** Hailey Clark, Josiah Guzman, Cameron Hill, Wasik Islam, Andrew Trujillo, Tom Malter, and Anthony Torres

**Milestone 1 due:** September 24, 2026

## Project

We are building a distributed lodging reservation system similar to Airbnb. Guests will be able to search properties and make reservations, while hosts will be able to create listings and manage availability.

For Milestone 1, we are starting with three backend services:

- Property Service
- Reservation Service
- Payment Service

The client starts the request. The basic flow for this milestone is:

```text
Client
  -> Property Service
  -> Reservation Service
  -> Payment Service
  -> Reservation result
```

We also use shared persistent storage for important data such as properties and reservations.

User Service and Review Service are planned for later milestones.

## Repository Structure

```text
.
├── docs/
│   ├── diagrams/
│   └── milestone-1/
│       ├── 01-system-overview.md
│       ├── 02-architecture.md
│       ├── 03-components.md
│       ├── 04-system-model.md
│       └── 05-communication-flow.md
├── src/
│   ├── client/
│   ├── property-service/
│   ├── reservation-service/
│   └── payment-service/
├── data/
├── logs/
├── screenshots/
└── README.md
```

## Milestone 1 Goal

The Milestone 1 prototype needs at least three communicating processes or services, a simple client request, a server response, and logs showing the messages exchanged.

## Clone the Repository

```bash
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging
```

## Working on the Project

Before starting work:

```bash
git pull
git checkout -b yourname-task
```

After making changes:

```bash
git add .
git commit -m "Describe what you changed"
git push -u origin yourname-task
```

Then open a pull request on GitHub so the change can be merged into `main`.
