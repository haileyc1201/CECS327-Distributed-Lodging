import socket
import json

HOST = "127.0.0.1"
PORT = 5002

def main():
    request = {
        "action": "check_availability",
        "property_id": 101
    }

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.connect((HOST, PORT))

        print(f"[CLIENT] Connected to Property Service at {HOST}:{PORT}")

        message = json.dumps(request).encode("utf-8")
        client_socket.sendall(message)

        print(f"[CLIENT] Sent: {request}")

        data = client_socket.recv(1024)

        response = json.loads(data.decode("utf-8"))

        print(f"[CLIENT] Received: {response}")


if __name__ == "__main__":
    main()

