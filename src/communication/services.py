"""Lodging nodes built on the communication layer.

* PropertyNode     - JSON-RPC server: property.get / property.list / availability.check
* ReservationNode  - JSON-RPC server: reservation.book / reservation.get / reservation.list.
                     Calls PropertyNode (request-reply), publishes ``booking.created``
                     (publish-subscribe) and multicasts an availability update to the
                     ``property-replicas`` group (group communication).
* subscriber handlers for notification / analytics / audit services
* replica handler for property cache replicas (group members)

Properties are read from data/properties.json (the same file Hailey's Milestone 1
Property Service uses). Availability changes are kept in memory so the shared
data file is not modified by demo runs.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from .broker import Publisher
from .codec import now_iso
from .group import multicast
from .rpc import RPCClient, RPCError, RPCServer

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"

PORTS = {
    "property": 6001,
    "reservation": 6002,
    "broker": 6010,
    "coordinator": 6020,
}
REPLICA_GROUP = "property-replicas"
BOOKING_TOPIC = "booking.created"


def load_properties() -> list[dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


class PropertyNode(RPCServer):
    def __init__(self, host="127.0.0.1", port=PORTS["property"]):
        super().__init__("property-rpc", host, port)
        self._props = {p["id"]: dict(p) for p in load_properties()}
        self._lock = threading.Lock()
        self.register("property.list", self.list)
        self.register("property.get", self.get)
        self.register("availability.check", self.check)
        self.register("property.set_available", self.set_available)

    def list(self):
        with self._lock:
            return list(self._props.values())

    def get(self, property_id: int):
        with self._lock:
            p = self._props.get(int(property_id))
        if p is None:
            raise RPCError(404, "Property not found", {"property_id": property_id})
        return p

    def check(self, property_id: int):
        p = self.get(property_id)
        return {"property_id": p["id"], "name": p["name"], "available": p["available"], "price": p["price"]}

    def set_available(self, property_id: int, available: bool):
        with self._lock:
            p = self._props.get(int(property_id))
            if p is None:
                raise RPCError(404, "Property not found", {"property_id": property_id})
            p["available"] = bool(available)
            return dict(p)


class ReservationNode(RPCServer):
    def __init__(self, host="127.0.0.1", port=PORTS["reservation"],
                 property_addr=("127.0.0.1", PORTS["property"]),
                 broker_addr=("127.0.0.1", PORTS["broker"]),
                 coordinator_addr=("127.0.0.1", PORTS["coordinator"])):
        super().__init__("reservation-rpc", host, port)
        self.property_addr, self.broker_addr, self.coordinator_addr = property_addr, broker_addr, coordinator_addr
        self.reservations: dict[str, dict] = {}
        self._book_lock = threading.Lock()
        self._property: RPCClient | None = None
        self._publisher: Publisher | None = None
        self.register("reservation.book", self.book)
        self.register("reservation.get", self.get)
        self.register("reservation.list", lambda: list(self.reservations.values()))

    def _prop(self) -> RPCClient:
        if self._property is None:
            self._property = RPCClient("reservation-rpc", *self.property_addr)
        return self._property

    def _pub(self) -> Publisher:
        if self._publisher is None:
            self._publisher = Publisher("reservation-rpc", *self.broker_addr)
        return self._publisher

    def get(self, reservation_id: str):
        r = self.reservations.get(reservation_id)
        if r is None:
            raise RPCError(404, "Reservation not found", {"reservation_id": reservation_id})
        return r

    def book(self, property_id: int, guest_name: str = "Guest", nights: int = 1):
        with self._book_lock:
            # 1) request-reply to the Property node
            avail = self._prop().call("availability.check", property_id=property_id)
            if not avail["available"]:
                return {"status": "rejected", "message": "Property is not available", "property_id": property_id}
            self._prop().call("property.set_available", property_id=property_id, available=False)
            res = {
                "reservation_id": "R-" + uuid.uuid4().hex[:8],
                "property_id": avail["property_id"],
                "property_name": avail["name"],
                "guest_name": guest_name,
                "nights": nights,
                "amount": avail["price"] * nights,
                "status": "confirmed",
                "created_at": now_iso(),
            }
            self.reservations[res["reservation_id"]] = res
        # 2) publish-subscribe: tell every interested service about the booking
        pub_ack = self._pub().publish(BOOKING_TOPIC, res)
        # 3) group communication: keep every property replica consistent
        grp_ack = multicast("reservation-rpc", *self.coordinator_addr, REPLICA_GROUP,
                            {"op": "availability_update", "property_id": res["property_id"], "available": False,
                             "reservation_id": res["reservation_id"]})
        return {"status": "accepted", "reservation": res,
                "notified_subscribers": pub_ack["delivered_to"],
                "replicas_updated": grp_ack["delivered_to"]}


def replica_handler(member, message: dict) -> None:
    """Applied on each property replica when a multicast arrives."""
    if message.get("op") == "availability_update":
        member.state[message["property_id"]] = message["available"]


SUBSCRIBERS = {
    "notification-service": "send confirmation email to {guest_name} for {property_name}",
    "analytics-service": "record revenue ${amount} for property {property_id}",
    "audit-service": "append audit record for {reservation_id}",
}
