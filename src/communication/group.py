"""Group communication: membership management + reliable multicast to N nodes.

A ``GroupCoordinator`` keeps the membership list for each named group. Every
``GroupMember`` runs its own TCP listener and joins by telling the coordinator
its address. ``multicast`` sends one message to the coordinator, which delivers
a numbered copy (``group.deliver``) to every current member and waits for each
``group.ack``. Members that cannot be reached are removed (simple failure
detection) and every membership change is announced to the group as a
``group.view`` message, so all members share the same view.

    member  -> coord   group.join      {"group", "member", "host", "port"}
    member  -> coord   group.leave     {"group", "member"}
    any     -> coord   group.members   {"group"}
    any     -> coord   group.multicast {"group", "message"}
    coord   -> member  group.deliver   {"group", "seq", "message", "origin"}
    member  -> coord   group.ack       {"seq", "member"}
    coord   -> member  group.view      {"group", "view_id", "members"}
"""
from __future__ import annotations

import itertools
import threading
from typing import Callable

from .codec import make_envelope
from .msglog import MessageLogger
from .server import FramedServer
from .transport import connect, recv_message, send_message


class GroupCoordinator(FramedServer):
    def __init__(self, name: str = "group-coordinator", host: str = "127.0.0.1", port: int = 0):
        super().__init__(name, host, port)
        self.groups: dict[str, dict[str, tuple[str, int]]] = {}
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._view = itertools.count(1)

    def members(self, group: str) -> list[str]:
        with self._lock:
            return sorted(self.groups.get(group, {}))

    def _deliver(self, member: str, addr: tuple[str, int], envelope: dict) -> bool:
        peer = f"{addr[0]}:{addr[1]}"
        try:
            with connect(*addr, timeout=3) as s:
                send_message(s, envelope, self.logger, peer)
                ack, _ = recv_message(s, self.logger, peer)
            return ack.get("type") == "group.ack"
        except OSError:
            return False

    def _fanout(self, group: str, msg_type: str, payload: dict) -> tuple[list[str], list[str]]:
        with self._lock:
            targets = dict(self.groups.get(group, {}))
        delivered, failed = [], []
        for member, addr in sorted(targets.items()):
            env = make_envelope(msg_type, self.name, payload, receiver=member)
            (delivered if self._deliver(member, addr, env) else failed).append(member)
        if failed:
            with self._lock:
                for m in failed:
                    self.groups.get(group, {}).pop(m, None)
            self.logger.info(f"removed unreachable members {failed} from {group}")
            self._announce_view(group)
        return delivered, failed

    def _announce_view(self, group: str) -> None:
        view = {"group": group, "view_id": next(self._view), "members": self.members(group)}
        self._fanout(group, "group.view", view)

    def handle(self, conn, message, fmt, peer) -> bool:
        kind, body = message.get("type"), message.get("payload") or {}
        group = body.get("group", "default")
        reply_body: dict
        if kind == "group.join":
            with self._lock:
                self.groups.setdefault(group, {})[body["member"]] = (body["host"], int(body["port"]))
            reply_body = {"group": group, "members": self.members(group)}
            reply_type = "group.join.ack"
        elif kind == "group.leave":
            with self._lock:
                self.groups.get(group, {}).pop(body["member"], None)
            reply_body = {"group": group, "members": self.members(group)}
            reply_type = "group.leave.ack"
        elif kind == "group.members":
            reply_body = {"group": group, "members": self.members(group)}
            reply_type = "group.members.reply"
        elif kind == "group.multicast":
            seq = next(self._seq)
            delivered, failed = self._fanout(group, "group.deliver",
                                             {"group": group, "seq": seq, "origin": message["sender"],
                                              "message": body.get("message")})
            reply_body = {"group": group, "seq": seq, "delivered_to": delivered, "failed": failed}
            reply_type = "group.multicast.ack"
        else:
            return False
        send_message(conn, make_envelope(reply_type, self.name, reply_body, receiver=message["sender"],
                                         correlation_id=message["id"]), self.logger, peer, fmt)
        if kind in ("group.join", "group.leave"):
            threading.Thread(target=self._announce_view, args=(group,), daemon=True).start()
        return True


def coordinator_request(sender: str, host: str, port: int, msg_type: str, payload: dict) -> dict:
    logger = MessageLogger(sender)
    with connect(host, port) as s:
        send_message(s, make_envelope(msg_type, sender, payload, receiver="group-coordinator"),
                     logger, f"{host}:{port}")
        reply, _ = recv_message(s, logger, f"{host}:{port}")
    return reply["payload"]


class GroupMember(FramedServer):
    """A node that belongs to a group and applies multicast messages to local state."""

    def __init__(self, name: str, group: str, coord_host: str, coord_port: int,
                 host: str = "127.0.0.1", port: int = 0,
                 on_message: Callable[["GroupMember", dict], None] | None = None):
        super().__init__(name, host, port)
        self.group, self.coord = group, (coord_host, coord_port)
        self.delivered: list[dict] = []
        self.view: list[str] = []
        self.on_message = on_message
        self.state: dict = {}

    def handle(self, conn, message, fmt, peer) -> bool:
        body = message.get("payload") or {}
        if message.get("type") == "group.deliver":
            self.delivered.append(body)
            if self.on_message:
                self.on_message(self, body["message"])
        elif message.get("type") == "group.view":
            self.view = body["members"]
        else:
            return False
        ack = make_envelope("group.ack", self.name, {"seq": body.get("seq", body.get("view_id")), "member": self.name},
                            receiver=message["sender"], correlation_id=message["id"])
        send_message(conn, ack, self.logger, peer, fmt)
        return False  # coordinator opens one connection per delivery

    def join(self) -> dict:
        return coordinator_request(self.name, *self.coord, "group.join",
                                   {"group": self.group, "member": self.name, "host": self.host, "port": self.port})

    def leave(self) -> dict:
        return coordinator_request(self.name, *self.coord, "group.leave", {"group": self.group, "member": self.name})


def multicast(sender: str, host: str, port: int, group: str, message: dict) -> dict:
    return coordinator_request(sender, host, port, "group.multicast", {"group": group, "message": message})
