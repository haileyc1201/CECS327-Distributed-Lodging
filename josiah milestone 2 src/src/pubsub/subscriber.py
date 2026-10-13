import socket
import sys
from pathlib import Path
 
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make src/ importable
 
from common.msglog import get_logger
from common.protocol import Message, MsgType, recv_message, send_message
 
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 5004
NAME = "SUBSCRIBER"
 
log = get_logger(NAME)
 
 
def main() -> None:
    patterns = sys.argv[1:] or ["*"]
    with socket.create_connection((BROKER_HOST, BROKER_PORT)) as sock:
        for pattern in patterns:
            send_message(sock, Message(MsgType.SUBSCRIBE, NAME, topic=pattern), log)
            recv_message(sock, log)  # ACK
        print(f"Subscribed to {patterns}. Waiting for events...")
 
        while True:
            msg = recv_message(sock, log)
            if msg is None:
                print("Broker closed the connection.")
                return
            if msg.type == MsgType.EVENT:
                print(f"[{msg.timestamp}] {msg.topic} from {msg.sender}: {msg.payload}")
 
 
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass