"""
HTTP API bridge so the React frontend can talk to the TCP microservices.
"""
import csv
import json
import socket
from pathlib import Path

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
except ImportError:
    print("Flask not installed. Run: pip install flask flask-cors")
    raise

HOST = "127.0.0.1"
PORT = 8000
RECV_BUFFER = 65536

PROPERTY_HOST = "127.0.0.1"
PROPERTY_PORT = 5001
RESERVATION_HOST = "127.0.0.1"
RESERVATION_PORT = 5002

ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = ROOT / "logs"
PROPERTIES_FILE = ROOT / "data" / "properties.csv"
RESERVATIONS_FILE = ROOT / "data" / "reservations.csv"

# Seed listings for Hard reset (102, 107, 112 start unavailable).
SEED_PROPERTIES = [
    {"id": "101", "name": "Long Beach Apartment", "price": "150", "available": "true", "city": "Long Beach", "beds": "2"},
    {"id": "102", "name": "Downtown Studio", "price": "120", "available": "false", "city": "Long Beach", "beds": "1"},
    {"id": "103", "name": "Beach House", "price": "275", "available": "true", "city": "Long Beach", "beds": "3"},
    {"id": "104", "name": "Belmont Shore Loft", "price": "195", "available": "true", "city": "Long Beach", "beds": "2"},
    {"id": "105", "name": "Campus Cottage", "price": "110", "available": "true", "city": "Long Beach", "beds": "1"},
    {"id": "106", "name": "Harbor View Condo", "price": "230", "available": "true", "city": "Long Beach", "beds": "2"},
    {"id": "107", "name": "Naples Canal Home", "price": "340", "available": "false", "city": "Long Beach", "beds": "4"},
    {"id": "108", "name": "Signal Hill Bungalow", "price": "165", "available": "true", "city": "Signal Hill", "beds": "2"},
    {"id": "109", "name": "Seal Beach Cabin", "price": "210", "available": "true", "city": "Seal Beach", "beds": "2"},
    {"id": "110", "name": "Arts District Flat", "price": "180", "available": "true", "city": "Los Angeles", "beds": "1"},
    {"id": "111", "name": "Koreatown Suite", "price": "140", "available": "true", "city": "Los Angeles", "beds": "1"},
    {"id": "112", "name": "Pasadena Guest House", "price": "255", "available": "false", "city": "Pasadena", "beds": "3"},
]

PROPERTY_FIELDS = ["id", "name", "price", "available", "city", "beds"]
RESERVATION_FIELDS = [
    "reservation_id",
    "property_id",
    "property_name",
    "guest_name",
    "amount",
    "payment_id",
    "refund_id",
    "status",
    "created_at",
    "cancelled_at",
]

app = Flask(__name__)
CORS(app)


def tcp_json(host, port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect((host, port))
        sock.sendall(json.dumps(payload).encode("utf-8"))
        data = sock.recv(RECV_BUFFER)
    return json.loads(data.decode("utf-8"))


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/properties")
def list_properties():
    try:
        result = tcp_json(PROPERTY_HOST, PROPERTY_PORT, {"action": "list_properties"})
        return jsonify(result)
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502


@app.get("/api/properties/<int:property_id>")
def get_property(property_id):
    try:
        result = tcp_json(PROPERTY_HOST, PROPERTY_PORT, {
            "action": "get_property",
            "property_id": property_id
        })
        status_code = 200 if result.get("status") == "success" else 404
        return jsonify(result), status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502


@app.post("/api/reservations")
def create_reservation():
    body = request.get_json(silent=True) or {}
    property_id = body.get("property_id")
    guest_name = body.get("guest_name", "Guest")

    if property_id is None:
        return jsonify({"status": "rejected", "message": "property_id is required"}), 400

    try:
        result = tcp_json(RESERVATION_HOST, RESERVATION_PORT, {
            "action": "book",
            "property_id": int(property_id),
            "guest_name": guest_name
        })
        status_code = 200 if result.get("status") == "accepted" else 400
        return jsonify(result), status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502


@app.get("/api/reservations")
def list_reservations():
    try:
        result = tcp_json(RESERVATION_HOST, RESERVATION_PORT, {"action": "list_reservations"})
        return jsonify(result)
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502


@app.post("/api/reservations/cancel")
def cancel_reservation():
    body = request.get_json(silent=True) or {}
    reservation_id = body.get("reservation_id")
    if not reservation_id:
        return jsonify({"status": "rejected", "message": "reservation_id is required"}), 400

    try:
        result = tcp_json(RESERVATION_HOST, RESERVATION_PORT, {
            "action": "cancel",
            "reservation_id": reservation_id
        })
        status_code = 200 if result.get("status") == "cancelled" else 400
        return jsonify(result), status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502


@app.delete("/api/reservations/<reservation_id>")
def delete_reservation(reservation_id):
    try:
        result = tcp_json(RESERVATION_HOST, RESERVATION_PORT, {
            "action": "cancel",
            "reservation_id": reservation_id
        })
        status_code = 200 if result.get("status") == "cancelled" else 400
        return jsonify(result), status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502


@app.post("/api/reset")
def reset_demo_data():
    """Restore seed properties.csv and clear reservations.csv (header only)."""
    try:
        PROPERTIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPERTIES_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=PROPERTY_FIELDS)
            writer.writeheader()
            writer.writerows(SEED_PROPERTIES)

        with open(RESERVATIONS_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RESERVATION_FIELDS)
            writer.writeheader()

        return jsonify({"status": "ok", "message": "Demo data reset"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/api/logs")
def get_logs():
    lines = []
    if LOGS_DIR.exists():
        for log_file in sorted(LOGS_DIR.glob("*.log")):
            try:
                content = log_file.read_text(encoding="utf-8").strip().splitlines()
                for line in content[-30:]:
                    lines.append({"file": log_file.name, "line": line})
            except OSError:
                continue
    return jsonify({"status": "ok", "logs": lines[-100:]})


def main():
    print(f"[GATEWAY] Listening on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
