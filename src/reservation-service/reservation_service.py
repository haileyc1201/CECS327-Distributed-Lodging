import socket
import json
import uuid
from pathlib import Path
from datetime import datetime

HOST = "127.0.0.1"
PORT = 5002
RECV_BUFFER = 65536

PROPERTY_HOST = "127.0.0.1"
PROPERTY_PORT = 5001
PAYMENT_HOST = "127.0.0.1"
PAYMENT_PORT = 5003

ROOT = Path(__file__).resolve().parents[2]
PROPERTIES_FILE = ROOT / "data" / "properties.json"
RESERVATIONS_FILE = ROOT / "data" / "reservations.json"
LOG_FILE = ROOT / "logs" / "reservation.log"


def log(message):
    line = f"[RESERVATION] {message}"
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


def tcp_request(host, port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((host, port))
        sock.sendall(json.dumps(payload).encode("utf-8"))
        data = sock.recv(RECV_BUFFER)
    return json.loads(data.decode("utf-8"))


def get_property(property_id):
    return tcp_request(PROPERTY_HOST, PROPERTY_PORT, {
        "action": "get_property",
        "property_id": property_id
    })


def process_payment(property_id, amount, guest_name):
    return tcp_request(PAYMENT_HOST, PAYMENT_PORT, {
        "action": "process_payment",
        "property_id": property_id,
        "amount": amount,
        "guest_name": guest_name
    })


def refund_payment(payment_id, amount, reservation_id):
    return tcp_request(PAYMENT_HOST, PAYMENT_PORT, {
        "action": "refund",
        "payment_id": payment_id,
        "amount": amount,
        "reservation_id": reservation_id
    })


def load_reservations():
    if not RESERVATIONS_FILE.exists():
        RESERVATIONS_FILE.write_text("[]\n", encoding="utf-8")
        return []
    with open(RESERVATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_reservations(reservations):
    with open(RESERVATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(reservations, f, indent=2)
        f.write("\n")


def set_property_available(property_id, available):
    with open(PROPERTIES_FILE, "r", encoding="utf-8") as f:
        properties = json.load(f)

    for prop in properties:
        if prop["id"] == property_id:
            prop["available"] = available
            break

    with open(PROPERTIES_FILE, "w", encoding="utf-8") as f:
        json.dump(properties, f, indent=2)
        f.write("\n")


def check_availability(property_id):
    property_response = get_property(property_id)
    log(f"Property Service replied: {property_response}")

    if property_response.get("status") != "success":
        return {
            "status": "rejected",
            "message": "Property does not exist"
        }

    if not property_response["property"].get("available"):
        return {
            "status": "rejected",
            "message": "Property is not available"
        }

    return {
        "status": "accepted",
        "message": "Property is available for reservation",
        "property": property_response["property"]
    }


def book_reservation(request):
    property_id = request.get("property_id")
    guest_name = request.get("guest_name", "Guest")

    if property_id is None:
        return {"status": "rejected", "message": "property_id is required"}

    property_response = get_property(property_id)
    log(f"Property Service replied: {property_response}")

    if property_response.get("status") != "success":
        return {"status": "rejected", "message": "Property does not exist"}

    prop = property_response["property"]
    if not prop.get("available"):
        return {"status": "rejected", "message": "Property is not available"}

    amount = prop.get("price", 0)
    payment_response = process_payment(property_id, amount, guest_name)
    log(f"Payment Service replied: {payment_response}")

    if payment_response.get("status") != "approved":
        return {
            "status": "rejected",
            "message": "Payment declined",
            "payment": payment_response
        }

    reservation_id = f"res-{uuid.uuid4().hex[:8]}"
    reservation = {
        "reservation_id": reservation_id,
        "property_id": property_id,
        "property_name": prop.get("name"),
        "guest_name": guest_name,
        "amount": amount,
        "payment_id": payment_response.get("payment_id"),
        "status": "confirmed",
        "created_at": datetime.now().isoformat()
    }

    reservations = load_reservations()
    reservations.append(reservation)
    save_reservations(reservations)
    set_property_available(property_id, False)
    log(f"Saved reservation {reservation_id} and marked property {property_id} unavailable")

    return {
        "status": "accepted",
        "message": "Reservation confirmed",
        "reservation": reservation,
        "payment": payment_response
    }


def list_reservations(include_cancelled=True):
    reservations = load_reservations()
    if include_cancelled:
        return {"status": "success", "reservations": reservations}
    active = [r for r in reservations if r.get("status", "confirmed") != "cancelled"]
    return {"status": "success", "reservations": active}


def cancel_reservation(request):
    reservation_id = request.get("reservation_id")
    if not reservation_id:
        return {"status": "rejected", "message": "reservation_id is required"}

    reservations = load_reservations()
    target = None
    for res in reservations:
        if res.get("reservation_id") == reservation_id:
            target = res
            break

    if target is None:
        return {"status": "rejected", "message": "Reservation not found"}

    if target.get("status") == "cancelled":
        return {
            "status": "rejected",
            "message": "Reservation already cancelled",
            "reservation": target
        }

    refund_response = None
    payment_id = target.get("payment_id")
    if payment_id:
        refund_response = refund_payment(
            payment_id,
            target.get("amount", 0),
            reservation_id
        )
        log(f"Payment Service refund replied: {refund_response}")
        if refund_response.get("status") != "refunded":
            return {
                "status": "rejected",
                "message": "Refund failed; reservation not cancelled",
                "refund": refund_response
            }

    target["status"] = "cancelled"
    target["cancelled_at"] = datetime.now().isoformat()
    if refund_response:
        target["refund_id"] = refund_response.get("refund_id")

    save_reservations(reservations)
    set_property_available(target["property_id"], True)
    log(f"Cancelled {reservation_id}; property {target['property_id']} available again")

    return {
        "status": "cancelled",
        "message": "Reservation cancelled and payment refunded",
        "reservation": target,
        "refund": refund_response
    }


def handle_client(connection, address):
    log(f"Connected by {address}")

    data = connection.recv(RECV_BUFFER)
    if not data:
        return

    request = json.loads(data.decode("utf-8"))
    log(f"Received: {request}")

    action = request.get("action", "check_availability")

    if action in ("book", "create_reservation"):
        response = book_reservation(request)
    elif action in ("cancel", "cancel_reservation"):
        response = cancel_reservation(request)
    elif action in ("list", "list_reservations"):
        response = list_reservations()
    elif action == "check_availability":
        property_id = request.get("property_id")
        if property_id is None:
            response = {"status": "rejected", "message": "property_id is required"}
        else:
            response = check_availability(property_id)
    else:
        if "property_id" in request:
            response = check_availability(request["property_id"])
        else:
            response = {"status": "rejected", "message": f"Unknown action: {action}"}

    connection.sendall(json.dumps(response).encode("utf-8"))
    log(f"Sent: {response}")


def main():
    load_reservations()

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
