import socket
import json
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5001

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"


def load_properties():
    with open(DATA_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def find_property(properties, property_id):
    for property_data in properties:
        if property_data["id"] == property_id:
            return property_data

    return None


def handle_client(connection, address):
    print(f"[PROPERTY] Connected by {address}")

    data = connection.recv(1024)

    if not data:
        return

    request = json.loads(data.decode("utf-8"))

    print(f"[PROPERTY] Received: {request}")

    properties = load_properties()

    property_id = request["property_id"]
    property_data = find_property(properties, property_id)

    if property_data is None:
        response = {
            "status": "error",
            "message": "Property not found"
        }
    else:
        response = {
            "status": "success",
            "property": property_data
        }

    connection.sendall(
        json.dumps(response).encode("utf-8")
    )

    print(f"[PROPERTY] Sent: {response}")


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, PORT))
        server_socket.listen()

        print(f"[PROPERTY] Listening on {HOST}:{PORT}")

        while True:
            connection, address = server_socket.accept()

            with connection:
                handle_client(connection, address)


if __name__ == "__main__":
    main()