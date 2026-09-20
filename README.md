# CECS327 Distributed Lodging

Semester project for **CECS 327: Introduction to Networks and Distributed Computing**.

## Project scope

This project is a distributed lodging-reservation system inspired by Airbnb.

The course requirements for this project include distributed management of:

- users
- properties
- availability
- reservations
- reviews
- payments

The system must also demonstrate:

- communication among services
- coordination of simultaneous booking requests
- replicated information
- transactional reservations
- recovery from failures

## Milestone 1: Architecture and Models

For Milestone 1, the group must:

- describe the purpose of the system
- identify the main services/components
- identify clients, servers, peers, and shared resources
- define the system model
- create an architecture diagram
- explain scalability, dependability, and resource sharing
- create a basic running skeleton with at least three communicating processes/services
- show a simple client request and server response
- log messages exchanged between components

See [docs/milestone-1/README.md](docs/milestone-1/README.md) for the working checklist.

## Repository layout

```text
.
├── docs/
│   ├── diagrams/
│   └── milestone-1/
├── src/
│   └── services/
├── logs/
├── screenshots/
├── CONTRIBUTING.md
└── README.md
```

The exact service breakdown is intentionally not locked in yet. The team should agree on the architecture before naming or implementing the final service folders.

## Clone the repository

```bash
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging
```

## Beginner workflow

Do not make large changes directly on `main`. Create a branch for your work:

```bash
git pull
git checkout -b yourname-task
```

After you make changes:

```bash
git status
git add .
git commit -m "Describe what you changed"
git push -u origin yourname-task
```

Then open a Pull Request on GitHub so the team can review and merge the work.

## Team rule

Before coding, agree on:

1. the three or more services/processes used in the Milestone 1 prototype
2. what each service owns
3. how they communicate
4. what request/response will be demonstrated
5. what data is shared or persistent

Keep the report, architecture diagram, and implementation consistent with one another.
