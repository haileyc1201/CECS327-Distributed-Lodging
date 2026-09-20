# Payment Service

Mock payment approval/rejection over TCP JSON on `127.0.0.1:5003`.

No real payment information is used.

## Run

```bash
# from repo root, with venv activated
python src/payment-service/payment_service.py
```

## Example request

```json
{
  "action": "process_payment",
  "property_id": 101,
  "amount": 150,
  "guest_name": "Tom"
}
```

## Example response

```json
{
  "status": "approved",
  "payment_id": "pay-abcd1234",
  "message": "Payment of $150.00 approved for Tom"
}
```

Approves when `amount > 0` and `property_id` is present; otherwise declines.
