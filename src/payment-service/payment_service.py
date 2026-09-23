import socket
import json
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5003

RESERVATION_HOST = "127.0.0.1"
RESERVATION_PORT = 5002

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"
PAYMENTS: list[dict] = [] # A simulated list of processed payments

def load_properties() -> list[dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_property_price(property_id: int) -> float | None: # Price per night, default none.
    for prop in load_properties():
        if prop["id"] == property_id:
            return prop.get("price_per_night")
    return None

def request_reservation(property_id) -> dict:  # Checks availability for a reservation.
    payload = {
        "action": "reserve",
        "property_id": property_id,
    }
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((RESERVATION_HOST, RESERVATION_PORT))
        sock.sendall(json.dumps(payload).encode("utf-8"))
        data = sock.recv(4096)
    return json.loads(data.decode("utf-8"))

def process_payment(property_id: int, nights: int, card_last4: str) -> dict:
    reservation = request_reservation(property_id)

    if reservation["status"] != "accepted":
        return {
            "status": "failed",
            "reason": "Could not determine property price",
        }

    price_per_night = get_property_price(property_id)
    if price_per_night is None:
        return {
            "status": "failed",
            "reason": "Could not determine property price",
        }

    total = round(price_per_night * nights, 2)

    charge_ok = _simulate_charge(card_last4, total)
    if not charge_ok:
        return {
            "status": "failed",
            "reason": "Card declined",
        }
    payment_id = len(PAYMENTS) + 1
    receipt = {
        "status": "success",
        "payment_id": payment_id,
        "property_id": property_id,
        "nights": nights,
        "price_per_night": price_per_night,
        "total_charged": total,
        "card_last4": card_last4,
        "message": f"Booking confirmed with a charge of ${total:.2f}. Enjoy your stay!"
    }
    PAYMENTS.append(receipt)
    return receipt

def _simulate_charge(card_last4: str, amount: float) -> bool: # Mock fraud card detection
    return card_last4 != "0000"

ACTIONS = {
    "pay",
    "list_payments",
}

def dispatch(request: dict) -> dict:
    action = request.get("action")
    if action == "pay":
        required = {"property_id", "nights", "card_last4"}
        missing = required - request.keys()
        if missing:
            return{
                "status": "error",
                "message": f"Missing fields: {', '.join(sorted(missing))}",
            }
        return process_payment(
            property_id = int(request["property_id"]),
            nights = int(request["nights"]),
            card_last4 = str(request["card_last4"]),
        )
    if action == "list_payments":
        return {
            "status": "success",
            "payments": PAYMENTS,
        }
    return {
        "status": "error",
        "message": "Unknown request..."
    }

def handle_client(connection: socket.socket, address: tuple) -> None:
    print(f"[PAYMENT] Connected by {address}")
    data = connection.recv(4096)
    if not data:
        return
    try:
        request = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        response = {"status": "error", "message": "Invalid JSON"}
        connection.sendall(json.dumps(response).encode("utf-8"))
        return
    print(f"[PAYMENT] Received: {request}")

    response = dispatch(request)

    connection.sendall(json.dumps(response).encode("utf-8"))
    print(f"[PAYMENT] Sent: {response}")

def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen()

        print(f"[PAYMENT] Listening on {HOST}:{PORT}")

        while True:
            connection, address = server_socket.accept()
            with connection:
                handle_client(connection, address)
if __name__ == "__main__":
    main()

