# System-Model Assumptions

## Organization

Distributed organization with centralized user interaction.

The system uses multiple backend services that communicate over a network, while the user sees one lodging reservation application.

## Timing

Semi-synchronous.

Requests are expected to normally complete within reasonable timing ranges, but delays can vary. Timeouts can be used, but a timeout does not automatically prove that a service crashed.

## Node Failures

Crash-recovery failures.

A service may stop unexpectedly and later restart. Important persistent information should still be available after restart.

## Link Failures

Communication may experience:

- delay
- packet or message loss
- temporary disconnection

A missing response does not automatically mean the other service crashed.

## Storage

Services may use local or volatile memory for temporary information. Important records such as listings and reservations should use persistent storage. Replication may be added later for availability and fault tolerance.
