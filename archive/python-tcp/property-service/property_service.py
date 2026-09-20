import socket
import json
import csv
from pathlib import Path
from datetime import datetime

HOST = "127.0.0.1"
PORT = 5001
RECV_BUFFER = 65536

ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "properties.csv"
LOG_FILE = ROOT / "logs" / "property.log"


def log(message):
    line = f"[PROPERTY] {message}"
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


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def load_properties():
    properties = []
    with open(DATA_FILE, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            properties.append({
                "id": int(row["id"]),
                "name": row["name"],
                "price": int(float(row["price"])),
                "available": _parse_bool(row["available"]),
                "city": row.get("city", ""),
                "beds": int(row["beds"]) if row.get("beds") not in (None, "") else 1,
            })
    return properties


def find_property(properties, property_id):
    for property_data in properties:
        if property_data["id"] == property_id:
            return property_data
    return None


def handle_get_property(request):
    property_id = request.get("property_id")
    if property_id is None:
        return {"status": "error", "message": "property_id is required"}

    properties = load_properties()
    property_data = find_property(properties, int(property_id))

    if property_data is None:
        return {"status": "error", "message": "Property not found"}

    return {"status": "success", "property": property_data}


def handle_list_properties():
    properties = load_properties()
    return {"status": "success", "properties": properties}


def handle_client(connection, address):
    log(f"Connected by {address}")

    data = connection.recv(RECV_BUFFER)
    if not data:
        return

    request = json.loads(data.decode("utf-8"))
    log(f"Received: {request}")

    action = request.get("action")

    if action in (None, "", "get_property", "check_availability"):
        if "property_id" in request:
            response = handle_get_property(request)
        elif action == "list_properties":
            response = handle_list_properties()
        else:
            response = {"status": "error", "message": "Unknown or missing action"}
    elif action == "list_properties":
        response = handle_list_properties()
    else:
        response = {"status": "error", "message": f"Unknown action: {action}"}

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
