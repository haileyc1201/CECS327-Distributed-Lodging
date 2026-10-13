import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make src/ importable

from common.msglog import get_logger
from common.protocol import (
    ProtocolError, make_error, make_reply, recv_message, send_message,
)

HOST = "127.0.0.1"
PORT = 5001
NAME = "PROPERTY"

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"

log = get_logger(NAME)


def load_properties():
    with open(DATA_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def find_property(properties, property_id):
    for property_data in properties:
        if property_data["id"] == property_id:
            return property_data
    return None


def handle_client(connection, address):
    log.info(f"Connected by {address}")

    try:
        request = recv_message(connection, log)
    except ProtocolError as exc:
        send_message(connection, make_error(None, NAME, str(exc)), log)
        return
    if request is None:
        return

    if request.action != "check_availability":
        send_message(connection, make_error(request, NAME, "Unknown action"), log)
        return

    property_id = request.payload.get("property_id")
    property_data = find_property(load_properties(), property_id)

    if property_data is None:
        reply = make_reply(request, NAME, status="error", message="Property not found")
    else:
        reply = make_reply(request, NAME, status="success", property=property_data)

    send_message(connection, reply, log)


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