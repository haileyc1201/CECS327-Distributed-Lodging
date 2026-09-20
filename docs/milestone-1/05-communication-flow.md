# Initial Communication Flow

1. Guest Client sends a property request to Property Service.
2. Property Service returns available property information.
3. Guest Client sends a booking request to Reservation Service.
4. Reservation Service verifies that the property and date are available.
5. Reservation Service sends a payment request to Payment Service.
6. Payment Service returns approval or rejection.
7. Reservation Service stores the reservation.
8. Reservation Service returns the booking result to the client.
9. Each service logs the messages it sends and receives.

This flow should be updated if the actual prototype ends up working differently.
