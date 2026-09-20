import socket
import json
import uuid
from pathlib import Path
from datetime import datetime

HOST = "127.0.0.1"
PORT = 5003
RECV_BUFFER = 65536

ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = ROOT / "logs" / "payment.log"


def log(message):
    line = f"[PAYMENT] {message}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "message": message
            }) + "\n")
    except OSError:
        pass


def process_payment(request):
    property_id = request.get("property_id")
    amount = request.get("amount")
    guest_name = request.get("guest_name", "Guest")

    payment_id = f"pay-{uuid.uuid4().hex[:8]}"

    if property_id is None:
        return {
            "status": "declined",
            "payment_id": payment_id,
            "message": "Missing property_id"
        }

    if amount is None:
        return {
            "status": "declined",
            "payment_id": payment_id,
            "message": "Missing amount"
        }

    try:
        amount_val = float(amount)
    except (TypeError, ValueError):
        return {
            "status": "declined",
            "payment_id": payment_id,
            "message": "Invalid amount"
        }

    if amount_val <= 0:
        return {
            "status": "declined",
            "payment_id": payment_id,
            "message": "Amount must be greater than 0"
        }

    return {
        "status": "approved",
        "payment_id": payment_id,
        "message": f"Payment of ${amount_val:.2f} approved for {guest_name}"
    }


def handle_client(connection, address):
    log(f"Connected by {address}")

    data = connection.recv(RECV_BUFFER)
    if not data:
        return

    request = json.loads(data.decode("utf-8"))
    log(f"Received: {request}")

    action = request.get("action", "process_payment")

    if action == "process_payment":
        response = process_payment(request)
    else:
        response = {
            "status": "declined",
            "payment_id": None,
            "message": f"Unknown action: {action}"
        }

    connection.sendall(json.dumps(response).encode("utf-8"))
    log(f"Sent: {response}")


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        log(f"Listening on {HOST}:{PORT}")

        while True:
            connection, address = server_socket.accept()
            with connection:
                try:
                    handle_client(connection, address)
                except Exception as exc:
                    log(f"Error handling client: {exc}")


if __name__ == "__main__":
    main()
