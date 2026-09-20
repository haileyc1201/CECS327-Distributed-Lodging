import socket
import json

HOST = "127.0.0.1"
PORT = 5002

PROPERTY_HOST = "127.0.0.1"
PROPERTY_PORT = 5001


def check_property(property_id):
    request = {
        "action": "check_availability",
        "property_id": property_id
    }

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((PROPERTY_HOST, PROPERTY_PORT))

        sock.sendall(
            json.dumps(request).encode("utf-8")
        )

        data = sock.recv(1024)

    return json.loads(data.decode("utf-8"))


def handle_client(connection, address):
    print(f"[RESERVATION] Connected by {address}")

    data = connection.recv(1024)

    if not data:
        return

    request = json.loads(data.decode("utf-8"))

    print(f"[RESERVATION] Received: {request}")

    property_id = request["property_id"]

    property_response = check_property(property_id)

    print(f"[RESERVATION] Property Service replied: {property_response}")

    if property_response["status"] != "success":
        response = {
            "status": "rejected",
            "message": "Property does not exist"
        }

    elif not property_response["property"]["available"]:
        response = {
            "status": "rejected",
            "message": "Property is not available"
        }

    else:
        response = {
            "status": "accepted",
            "message": "Property is available for reservation"
        }

    connection.sendall(
        json.dumps(response).encode("utf-8")
    )

    print(f"[RESERVATION] Sent: {response}")


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, PORT))
        server_socket.listen()

        print(f"[RESERVATION] Listening on {HOST}:{PORT}")

        while True:
            connection, address = server_socket.accept()

            with connection:
                handle_client(connection, address)


if __name__ == "__main__":
    main()