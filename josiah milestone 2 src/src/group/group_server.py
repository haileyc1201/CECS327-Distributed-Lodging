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
PORT = 5005
NAME = "GROUP"

log = get_logger(NAME)

_lock = threading.Lock()
_groups: dict[str, dict[str, socket.socket]] = {}  # group -> {member_id: socket}
_seq: dict[str, int] = {}                          # group -> last sequence number


def _multicast(group: str, sender: str, payload: dict, exclude: str | None = None) -> int:
    _seq[group] = _seq.get(group, 0) + 1
    out = Message(MsgType.GROUP_MSG, sender, group=group, payload={**payload, "seq": _seq[group]})
    delivered = 0
    for member, sock in list(_groups.get(group, {}).items()):
        if member == exclude:
            continue
        try:
            send_message(sock, out, log)
            delivered += 1
        except OSError:
            _groups[group].pop(member, None)
    return delivered


def handle_client(connection: socket.socket, address: tuple) -> None:
    log.info(f"Connected by {address}")
    joined: set[tuple[str, str]] = set()  # (group, member_id) pairs this connection owns
    try:
        while True:
            try:
                msg = recv_message(connection, log)
            except ProtocolError as exc:
                send_message(connection, make_error(None, NAME, str(exc)), log)
                return
            if msg is None:
                return
            if not msg.group:
                send_message(connection, make_error(msg, NAME, "group is required"), log)
                continue

            if msg.type == MsgType.JOIN:
                with _lock:
                    _groups.setdefault(msg.group, {})[msg.sender] = connection
                    joined.add((msg.group, msg.sender))
                    members = sorted(_groups[msg.group])
                    send_message(connection, Message(MsgType.ACK, NAME, group=msg.group,
                                                     correlation_id=msg.msg_id,
                                                     payload={"members": members}), log)
                    _multicast(msg.group, NAME, {"event": "joined", "member": msg.sender},
                               exclude=msg.sender)

            elif msg.type == MsgType.LEAVE:
                with _lock:
                    _groups.get(msg.group, {}).pop(msg.sender, None)
                    joined.discard((msg.group, msg.sender))
                    _multicast(msg.group, NAME, {"event": "left", "member": msg.sender})
                send_message(connection, Message(MsgType.ACK, NAME, group=msg.group,
                                                 correlation_id=msg.msg_id), log)

            elif msg.type == MsgType.GROUP_MSG:
                with _lock:
                    if msg.sender not in _groups.get(msg.group, {}):
                        send_message(connection, make_error(msg, NAME, "join the group first"), log)
                        continue
                    count = _multicast(msg.group, msg.sender, msg.payload, exclude=msg.sender)
                    send_message(connection, Message(MsgType.ACK, NAME, group=msg.group,
                                                     correlation_id=msg.msg_id,
                                                     payload={"delivered_to": count}), log)
            else:
                send_message(connection, make_error(msg, NAME, "Unsupported message for group server"), log)
    except OSError:
        pass
    finally:
        with _lock:
            for group, member in joined:
                _groups.get(group, {}).pop(member, None)
                _multicast(group, NAME, {"event": "left", "member": member})
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