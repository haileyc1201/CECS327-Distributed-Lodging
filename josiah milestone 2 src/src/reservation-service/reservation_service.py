import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make src/ importable

from common.msglog import get_logger
from common.protocol import (
    ProtocolError, call, make_error, make_reply, make_request,
    publish, recv_message, send_message,
)

HOST = "127.0.0.1"
PORT = 5002
NAME = "RESERVATION"

PROPERTY_HOST = "127.0.0.1"
PROPERTY_PORT = 5001

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 5004

log = get_logger(NAME)


def check_property(property_id):
    """Request-reply call to the Property Service."""
    request = make_request(NAME, "check_availability", property_id=property_id)
    return call(PROPERTY_HOST, PROPERTY_PORT, request, log).payload


def handle_client(connection, address):
    log.info(f"Connected by {address}")

    try:
        request = recv_message(connection, log)
    except ProtocolError as exc:
        send_message(connection, make_error(None, NAME, str(exc)), log)
        return
    if request is None:
        return

    # Accept "reserve" (what the Payment Service sends) and "check_availability"
    # (what the test client sends).
    if request.action not in ("reserve", "check_availability"):
        send_message(connection, make_error(request, NAME, "Unknown action"), log)
        return

    property_id = request.payload.get("property_id")

    try:
        property_response = check_property(property_id)
    except (OSError, ProtocolError) as exc:
        send_message(connection, make_error(request, NAME, f"Property Service unavailable: {exc}"), log)
        return

    if property_response["status"] != "success":
        reply = make_reply(request, NAME, status="rejected", message="Property does not exist")
    elif not property_response["property"]["available"]:
        reply = make_reply(request, NAME, status="rejected", message="Property is not available")
    else:
        reply = make_reply(request, NAME, status="accepted",
                           message="Property is available for reservation")

    send_message(connection, reply, log)

    # Pub-sub: tell any interested subscribers what happened.
    publish(BROKER_HOST, BROKER_PORT, f"reservations.{reply.payload['status']}", NAME, log,
            property_id=property_id)


def main():
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