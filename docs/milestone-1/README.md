# Milestone 1 — Architecture and Models

Use this file as the team's working checklist. It is an outline, not finished report prose.

## Report sections

### 1. System overview

Decide and document:

- What problem does the lodging system solve?
- Who are the users?
- What can guests do?
- What can hosts do?
- What does the distributed backend manage?

### 2. Architecture diagram

The final diagram should show:

- clients
- at least three communicating processes/services
- communication paths
- shared resources / persistent storage
- any server or peer roles the group chooses

Store the final diagram in `docs/diagrams/`.

### 3. Description of components

For every component, record:

- name
- responsibility
- whether it acts as a client, server, or peer
- what data/resources it uses
- what other components it communicates with

### 4. System-model assumptions

The report must state the team's assumptions about:

- centralized, decentralized, or distributed organization
- synchronous, asynchronous, or semi-synchronous timing
- node failures
- link failures
- storage / persistence

Do not mark these as final until the group agrees on them.

### 5. Initial communication flow

Describe one complete request/response path used in the prototype.

Example structure only:

```text
Client
  -> Service A
  -> Service B
  -> Service C
  -> response
```

Replace Service A/B/C with the team's actual design.

## Required design discussion

Explain how the design supports:

- scalability
- dependability
- resource sharing

For this project, the team should explicitly think about simultaneous attempts to reserve the same property and dates.

## Prototype checklist

- [ ] At least three communicating processes/services
- [ ] Simple client request
- [ ] Simple server response
- [ ] Message logging
- [ ] Running prototype demonstrated
- [ ] Logs saved in `logs/`
- [ ] Screenshots saved in `screenshots/`

## Submission checklist

- [ ] PDF report
- [ ] Video link/upload
- [ ] Source-code repository
- [ ] README
- [ ] Screenshots or logs
- [ ] Contribution table

## README details to add after implementation is decided

- required software
- dependency installation
- how to start each service
- how to run the demo
- how to reproduce test cases
