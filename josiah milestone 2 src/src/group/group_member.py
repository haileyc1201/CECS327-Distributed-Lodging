import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make src/ importable

from common.msglog import get_logger
from common.protocol import Message, MsgType, recv_message, send_message

GROUP_HOST = "127.0.0.1"
GROUP_PORT = 5005


def listen(sock: socket.socket, log) -> None:
    try:
        while True:
            msg = recv_message(sock, log)
            if msg is None:
                print("\n[server closed the connection]")
                return
            if msg.type == MsgType.GROUP_MSG:
                p = msg.payload
                if "event" in p:
                    print(f"\n* {p['member']} {p['event']} {msg.group} (seq {p['seq']})")
                else:
                    print(f"\n[{msg.group} #{p['seq']}] {msg.sender}: {p.get('text')}")
            elif msg.type == MsgType.ERROR:
                print(f"\n! {msg.payload.get('message')}")
    except OSError:
        pass


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python group_member.py <member-name> [group-name]")
    name = sys.argv[1]
    group = sys.argv[2] if len(sys.argv) > 2 else "guests"
    log = get_logger(f"MEMBER-{name}")

    with socket.create_connection((GROUP_HOST, GROUP_PORT)) as sock:
        send_message(sock, Message(MsgType.JOIN, name, group=group), log)
        threading.Thread(target=listen, args=(sock, log), daemon=True).start()
        print(f"Joined '{group}' as {name}.")

        try:
            for line in sys.stdin:
                text = line.strip()
                if text:
                    send_message(sock, Message(MsgType.GROUP_MSG, name, group=group,
                                               payload={"text": text}), log)
        except KeyboardInterrupt:
            pass
        send_message(sock, Message(MsgType.LEAVE, name, group=group), log)


if __name__ == "__main__":
    main()