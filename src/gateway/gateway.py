"""
HTTP API bridge so the React frontend can talk to the TCP microservices.
"""
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
