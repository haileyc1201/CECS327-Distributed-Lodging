import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make src/ importable

from common.msglog import get_logger
from common.protocol import (
    Message, ProtocolError, call, make_error, make_reply, make_request,
    publish, recv_message, send_message,
)

HOST = "127.0.0.1"
PORT = 5003
NAME = "PAYMENT"

RESERVATION_HOST = "127.0.0.1"
RESERVATION_PORT = 5002

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 5004

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"
PAYMENTS: list[dict] = []  # A simulated list of processed payments

log = get_logger(NAME)


def load_properties() -> list[dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_property_price(property_id: int) -> float | None:  # Price per night, default none.
    for prop in load_properties():
        if prop["id"] == property_id:
            return prop.get("price")
    return None


def request_reservation(property_id: int) -> dict:  # Checks availability for a reservation.
    request = make_request(NAME, "reserve", property_id=property_id)
    return call(RESERVATION_HOST, RESERVATION_PORT, request, log).payload


def process_payment(property_id: int, nights: int, card_last4: str) -> dict:
    try:
        reservation = request_reservation(property_id)
    except (OSError, ProtocolError) as exc:
        return {"status": "failed", "reason": f"Reservation Service unavailable: {exc}"}

    if reservation.get("status") != "accepted":
        return {
            "status": "failed",
            "reason": reservation.get("message", "Reservation was not accepted"),
        }

    price_per_night = get_property_price(property_id)
    if price_per_night is None:
        return {"status": "failed", "reason": "Could not determine property price"}

    total = round(price_per_night * nights, 2)

    if not _simulate_charge(card_last4, total):
        return {"status": "failed", "reason": "Card declined"}

    payment_id = len(PAYMENTS) + 1
    receipt = {
        "status": "success",
        "payment_id": payment_id,
        "property_id": property_id,
        "nights": nights,
        "price_per_night": price_per_night,
        "total_charged": total,
        "card_last4": card_last4,
        "message": f"Booking confirmed with a charge of ${total:.2f}. Enjoy your stay!",
    }
    PAYMENTS.append(receipt)
    return receipt


def _simulate_charge(card_last4: str, amount: float) -> bool:  # Mock fraud card detection
    return card_last4 != "0000"


def dispatch(request: Message) -> Message:
    payload = request.payload

    if request.action == "pay":
        required = {"property_id", "nights", "card_last4"}
        missing = required - payload.keys()
        if missing:
            return make_error(request, NAME, f"Missing fields: {', '.join(sorted(missing))}")
        try:
            result = process_payment(
                property_id=int(payload["property_id"]),
                nights=int(payload["nights"]),
                card_last4=str(payload["card_last4"]),
            )
        except (TypeError, ValueError):
            return make_error(request, NAME, "property_id and nights must be integers")

        outcome = "completed" if result["status"] == "success" else "failed"
        publish(BROKER_HOST, BROKER_PORT, f"payments.{outcome}", NAME, log,
                property_id=payload["property_id"], status=result["status"])
        return make_reply(request, NAME, **result)

    if request.action == "list_payments":
        return make_reply(request, NAME, status="success", payments=PAYMENTS)

    return make_error(request, NAME, "Unknown request...")


def handle_client(connection: socket.socket, address: tuple) -> None:
    log.info(f"Connected by {address}")

    try:
        request = recv_message(connection, log)
    except ProtocolError as exc:
        send_message(connection, make_error(None, NAME, str(exc)), log)
        return
    if request is None:
        return

    send_message(connection, dispatch(request), log)


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen()

        log.info(f"Listening on {HOST}:{PORT}")

        while True:
            connection, address = server_socket.accept()
            with connection:
                handle_client(connection, address)


if __name__ == "__main__":
    main()