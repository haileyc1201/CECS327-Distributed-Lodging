"""Small threaded TCP server base used by every node."""
from __future__ import annotations

import socket
import threading

from .msglog import MessageLogger
from .transport import ConnectionClosed, listen, recv_message


class FramedServer:
    """Accepts connections and calls ``handle(sock, message, fmt, peer)`` for every frame."""

    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 0):
        self.name = name
        self.logger = MessageLogger(name)
        self.clock = self.logger.clock          # the node's Lamport clock
        self._sock = listen(host, port)
        self.host, self.port = self._sock.getsockname()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # subclasses override
    def handle(self, conn: socket.socket, message: dict, fmt: str, peer: str) -> bool:
        """Return False to close the connection after this message."""
        raise NotImplementedError

    def on_disconnect(self, conn: socket.socket) -> None:
        pass

    def _serve_conn(self, conn: socket.socket, addr) -> None:
        peer = f"{addr[0]}:{addr[1]}"
        try:
            with conn:
                while not self._stop.is_set():
                    try:
                        message, fmt = recv_message(conn, self.logger, peer)
                    except (ConnectionClosed, ConnectionResetError, OSError):
                        break
                    except ValueError as exc:            # malformed frame or invalid Lamport stamp
                        self.logger.info(f"rejected an invalid message from {peer}: {exc}",
                                         invalid={"peer": peer, "reason": str(exc)})
                        break
                    if not self.handle(conn, message, fmt, peer):
                        break
        finally:
            self.on_disconnect(conn)

    def serve_forever(self) -> None:
        if self._stop.is_set():
            return
        with self.logger.event_lock:
            # Startup is the node's initial state, not a logical event: a fresh node logs it at lc 0
            # (its clock stays at 0 until the first real event); a reused name just ticks.
            self.logger.info(f"listening on {self.host}:{self.port}", stamp=0 if self.clock.time == 0 else None)
        try:
            self._sock.settimeout(0.1)
        except OSError:                  # stop() closed the socket before this thread got going (WinError 10038 on Windows)
            return
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(None)
            threading.Thread(target=self._serve_conn, args=(conn, addr), daemon=True).start()

    def start(self) -> "FramedServer":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
