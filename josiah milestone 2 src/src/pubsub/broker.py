import fnmatch
import socket
import sys
import threading
from pathlib import Path
 
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make src/ importable
 
from common.msglog import get_logger
from common.protocol import (
    Message, MsgType, ProtocolError, make_error, recv_message, send_message,
)
 
HOST = "127.0.0.1"
PORT = 5004
NAME = "BROKER"
 
log = get_logger(NAME)
 
_lock = threading.Lock()
_subscriptions: dict[socket.socket, set[str]] = {}  # subscriber socket -> topic patterns
 
 
def _deliver(event: Message) -> int:
    delivered = 0
    with _lock:
        for sock, patterns in list(_subscriptions.items()):
            if any(fnmatch.fnmatch(event.topic, p) for p in patterns):
                try:
                    send_message(sock, event, log)
                    delivered += 1
                except OSError:
                    _subscriptions.pop(sock, None)
    return delivered
 
 
def handle_client(connection: socket.socket, address: tuple) -> None:
    log.info(f"Connected by {address}")
    try:
        while True:
            try:
                msg = recv_message(connection, log)
            except ProtocolError as exc:
                send_message(connection, make_error(None, NAME, str(exc)), log)
                return
            if msg is None:
                return
 
            if msg.type == MsgType.SUBSCRIBE and msg.topic:
                with _lock:
                    _subscriptions.setdefault(connection, set()).add(msg.topic)
                send_message(connection, Message(MsgType.ACK, NAME, correlation_id=msg.msg_id,
                                                 topic=msg.topic), log)
 
            elif msg.type == MsgType.UNSUBSCRIBE and msg.topic:
                with _lock:
                    _subscriptions.get(connection, set()).discard(msg.topic)
                send_message(connection, Message(MsgType.ACK, NAME, correlation_id=msg.msg_id,
                                                 topic=msg.topic), log)
 
            elif msg.type == MsgType.PUBLISH and msg.topic:
                event = Message(MsgType.EVENT, msg.sender, payload=msg.payload,
                                topic=msg.topic, correlation_id=msg.msg_id)
                count = _deliver(event)
                send_message(connection, Message(MsgType.ACK, NAME, correlation_id=msg.msg_id,
                                                 topic=msg.topic, payload={"delivered_to": count}), log)
 
            else:
                send_message(connection, make_error(msg, NAME, "Unsupported message for broker"), log)
    except OSError:
        pass
    finally:
        with _lock:
            _subscriptions.pop(connection, None)
        connection.close()
        log.info(f"Disconnected {address}")
 
 
def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        log.info(f"Listening on {HOST}:{PORT}")
 
        while True:
            connection, address = server_socket.accept()
            threading.Thread(target=handle_client, args=(connection, address), daemon=True).start()
 
 
if __name__ == "__main__":
    main()