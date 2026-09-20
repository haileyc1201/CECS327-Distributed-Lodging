"""
Simple TCP demo client for Milestone 1.
Primary demo UI is the React frontend; this client is useful for quick socket tests.
"""
import socket
import json
import sys

PROPERTY_HOST = "127.0.0.1"
PROPERTY_PORT = 5001
RESERVATION_HOST = "127.0.0.1"
RESERVATION_PORT = 5002
RECV_BUFFER = 65536


def tcp_json(host, port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((host, port))
        sock.sendall(json.dumps(payload).encode("utf-8"))
        data = sock.recv(RECV_BUFFER)
    return json.loads(data.decode("utf-8"))


def list_properties():
    print("[CLIENT] Listing properties via Property Service...")
    response = tcp_json(PROPERTY_HOST, PROPERTY_PORT, {"action": "list_properties"})
    print(f"[CLIENT] Received: {json.dumps(response, indent=2)}")
    return response


def check_availability(property_id):
    print(f"[CLIENT] Checking availability for property {property_id}...")
    response = tcp_json(RESERVATION_HOST, RESERVATION_PORT, {
        "action": "check_availability",
        "property_id": property_id
    })
    print(f"[CLIENT] Received: {json.dumps(response, indent=2)}")
    return response


def book(property_id, guest_name="Tom"):
    print(f"[CLIENT] Booking property {property_id} for {guest_name}...")
    response = tcp_json(RESERVATION_HOST, RESERVATION_PORT, {
        "action": "book",
        "property_id": property_id,
        "guest_name": guest_name
    })
    print(f"[CLIENT] Received: {json.dumps(response, indent=2)}")
    return response


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    property_id = int(sys.argv[2]) if len(sys.argv) > 2 else 101
    guest_name = sys.argv[3] if len(sys.argv) > 3 else "Tom"

    if mode == "list":
        list_properties()
    elif mode == "book":
        book(property_id, guest_name)
    else:
        check_availability(property_id)


if __name__ == "__main__":
    main()
