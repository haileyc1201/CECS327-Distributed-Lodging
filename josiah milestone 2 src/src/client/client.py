import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.msglog import get_logger
from common.protocol import call, make_request

NAME = "CLIENT"
RESERVATION = ("127.0.0.1", 5002)
PAYMENT = ("127.0.0.1", 5003)

log = get_logger(NAME)


def main() -> None:
    reply = call(*RESERVATION, make_request(NAME, "check_availability", property_id=101), log)
    print("Availability:", reply.type.value, reply.payload)

    reply = call(*PAYMENT, make_request(NAME, "pay", property_id=101, nights=3, card_last4="4242"), log)
    print("Payment:", reply.type.value, reply.payload)

    reply = call(*PAYMENT, make_request(NAME, "pay", property_id=102, nights=2, card_last4="4242"), log)
    print("Unavailable property:", reply.type.value, reply.payload)

    reply = call(*PAYMENT, make_request(NAME, "list_payments"), log)
    print("All payments:", reply.payload)


if __name__ == "__main__":
    main()