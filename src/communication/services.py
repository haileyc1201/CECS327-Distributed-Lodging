"""Lodging nodes built on the communication layer.

* PropertyNode     - JSON-RPC server: property.get / property.list / availability.check.
                     Property records live either in memory (default) or, when given a
                     RingClient, in the ring overlay (see ring.py), so they survive peers
                     joining, leaving and crashing.
* ReservationNode  - JSON-RPC server: reservation.book / reservation.get / reservation.list /
                     reservation.status.
                     Reservations live in memory (default) or in the ring overlay when given
                     a RingClient (key ``reservation:<id>`` plus an index key).
                     Calls PropertyNode (request-reply), publishes ``booking.created``
                     (publish-subscribe) and multicasts an availability update to the
                     ``property-replicas`` group (group communication).

                     Cluster mode (``node_id`` given): several ReservationNodes run side by side.
                     Each embeds a CoordinationNode (node.py) that shares its logical clock:
                       - Bully election picks a leader (the highest node_id alive); the leader
                         announces itself on the ``cluster.leader`` topic and every node reports
                         it in ``reservation.status``.
                       - A booking is a critical section: check availability -> mark unavailable
                         -> save. Ricart-Agrawala mutual exclusion makes that section exclusive
                         across ALL reservation nodes, so two nodes can never sell the same
                         property or overwrite each other's reservation-index update.
* subscriber handlers for notification / analytics / audit services
* replica handler for property cache replicas (group members)

Properties are read from data/properties.json (the same file Hailey's Milestone 1
Property Service uses). Availability changes are kept in memory (or in the ring) so
the shared data file is not modified by demo runs.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .broker import Publisher
from .codec import make_envelope, now_iso
from .node import CoordinationNode
from .ring import RingClient
from .rpc import RPCClient, RPCError, RPCServer
from .transport import connect, recv_message, send_message

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "properties.json"

PORTS = {
    "property": 6001,
    "reservation": 6002,
    "broker": 6010,
    "coordinator": 6020,
}
RING_PORTS = {"ring-A": 6301, "ring-B": 6302, "ring-C": 6303, "ring-D": 6304}
# Reservation cluster: name -> rank in the Bully election, client-facing RPC port, coordination port
RESERVATION_NODES = {
    "reservation-A": {"id": 1, "rpc": 6031, "coord": 6501},
    "reservation-B": {"id": 2, "rpc": 6032, "coord": 6502},
    "reservation-C": {"id": 3, "rpc": 6033, "coord": 6503},
}
REPLICA_GROUP = "property-replicas"
BOOKING_TOPIC = "booking.created"
LEADER_TOPIC = "cluster.leader"
RES_INDEX = "reservations:index"   # ring key holding the list of reservation ids


def load_properties() -> list[dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cluster_peers(host: str = "127.0.0.1") -> list[dict]:
    """The coordination addresses of every reservation node, as CoordinationNode peers."""
    return [{"name": n, "id": c["id"], "host": host, "port": c["coord"]} for n, c in RESERVATION_NODES.items()]


class PropertyNode(RPCServer):
    def __init__(self, host="127.0.0.1", port=PORTS["property"], ring: RingClient | None = None):
        super().__init__("property-rpc", host, port)
        self._ring = ring
        self._lock = threading.Lock()
        seed = {p["id"]: dict(p) for p in load_properties()}
        if ring is None:
            self._props = seed
        else:
            self._ids = sorted(seed)
            for pid, prop in seed.items():
                if not ring.get(str(pid))["found"]:   # load once; keeps bookings that survived a restart
                    ring.put(str(pid), prop)
        self.register("property.list", self.list)
        self.register("property.get", self.get)
        self.register("availability.check", self.check)
        self.register("property.set_available", self.set_available)

    # storage: in-memory dict, or the ring overlay when one is configured
    def _load(self, property_id: int) -> dict | None:
        if self._ring is None:
            p = self._props.get(property_id)
            return dict(p) if p else None
        r = self._ring.get(str(property_id))
        return r["value"] if r["found"] else None

    def _save(self, prop: dict) -> None:
        if self._ring is None:
            self._props[prop["id"]] = prop
        else:
            self._ring.put(str(prop["id"]), prop)

    def list(self):
        with self._lock:
            ids = list(self._props) if self._ring is None else self._ids
            return [p for p in (self._load(i) for i in ids) if p]

    def get(self, property_id: int):
        with self._lock:
            p = self._load(int(property_id))
        if p is None:
            raise RPCError(404, "Property not found", {"property_id": property_id})
        return p

    def check(self, property_id: int):
        p = self.get(property_id)
        return {"property_id": p["id"], "name": p["name"], "available": p["available"], "price": p["price"]}

    def set_available(self, property_id: int, available: bool):
        with self._lock:
            p = self._load(int(property_id))
            if p is None:
                raise RPCError(404, "Property not found", {"property_id": property_id})
            p["available"] = bool(available)
            self._save(p)
            return dict(p)


class ReservationNode(RPCServer):
    def __init__(self, host="127.0.0.1", port=PORTS["reservation"],
                 property_addr=("127.0.0.1", PORTS["property"]),
                 broker_addr=("127.0.0.1", PORTS["broker"]),
                 coordinator_addr=("127.0.0.1", PORTS["coordinator"]),
                 ring: RingClient | None = None,
                 name: str = "reservation-rpc",
                 node_id: int | None = None, coord_port: int = 0, cluster: list[dict] | None = None,
                 election_monitor: float | None = 0.5, use_mutex: bool = True, book_delay: float = 0.0):
        """Single node by default. Pass ``node_id`` to make it one member of a reservation cluster.

        cluster           coordination addresses of the cluster ([{"name","id","host","port"}]); may also be
                          given later with ``join_cluster`` (tests with ephemeral ports do that)
        election_monitor  heartbeat interval of the Bully monitor; None = do not start it automatically
        use_mutex         False disables the distributed mutex (only to demonstrate the race it prevents)
        book_delay        seconds of simulated processing between the availability check and the update
        """
        super().__init__(name, host, port)
        self.property_addr, self.broker_addr, self.coordinator_addr = property_addr, broker_addr, coordinator_addr
        self._ring = ring
        if ring is not None:
            ring.logger = self.logger             # the ring client acts for this node: same logical clock
        self.reservations: dict[str, dict] = {}   # used only when there is no ring
        self._book_lock = threading.Lock()        # one booking at a time on THIS node
        self._property: RPCClient | None = None
        self._publisher: Publisher | None = None
        self.use_mutex, self.book_delay, self.election_monitor = use_mutex, book_delay, election_monitor
        self.coord: CoordinationNode | None = None
        if node_id is not None:
            # the coordination endpoint shares this node's logger, hence its single Lamport clock
            self.coord = CoordinationNode(name, node_id, host, coord_port, logger=self.logger)
            self.coord.election.on_leader = self._on_leader
            if cluster:
                self.join_cluster(cluster)
        self.register("reservation.book", self.book)
        self.register("reservation.get", self.get)
        self.register("reservation.list", self.list_reservations)
        self.register("reservation.status", self.status)

    # ------------------------------------------------------------ cluster

    def join_cluster(self, nodes: list[dict]) -> None:
        """Tell this node about the other reservation nodes (itself may be in the list)."""
        if self.coord is None:
            raise RuntimeError("not a cluster node: construct ReservationNode with node_id=...")
        self.coord.set_peers(nodes)

    def serve_forever(self) -> None:
        if self.coord is not None:
            self.coord.start()
            if self.election_monitor:
                self.coord.election.start_monitor(self.election_monitor)   # no leader -> elects one
        super().serve_forever()

    def stop(self) -> None:
        if self.coord is not None:
            self.coord.stop()
        for c in (self._property, self._publisher):          # connections opened lazily by book()
            if c is not None:
                try:
                    c.close()
                except OSError:
                    pass
        super().stop()

    def status(self):
        el = self.coord.election if self.coord else None
        return {"name": self.name, "clustered": self.coord is not None,
                "leader": el.leader_name if el else None, "is_leader": bool(el and el.is_leader),
                "lc": self.logger.clock.time}

    def _on_leader(self, leader: dict) -> None:
        """Election hook: the node that became leader announces it to everybody on the broker."""
        if leader["name"] != self.name:
            return
        try:
            self._pub().publish(LEADER_TOPIC, {"leader": self.name, "id": leader["id"], "lc": self.logger.clock.time})
        except OSError as exc:
            self.logger.info(f"could not announce leadership on the broker: {exc}")
            self._publisher = None

    @contextmanager
    def _exclusive(self):
        """The booking critical section: one thread here, and (cluster mode) one node in the whole cluster."""
        with self._book_lock:                     # Ricart-Agrawala allows one requester per node
            if self.coord is not None and self.use_mutex:
                with self.coord.mutex.critical_section():
                    yield
            else:
                yield

    # ------------------------------------------------------------ plumbing

    def _prop(self) -> RPCClient:
        if self._property is None:
            self._property = RPCClient(self.name, *self.property_addr, logger=self.logger)
        return self._property

    def _pub(self) -> Publisher:
        if self._publisher is None:
            self._publisher = Publisher(self.name, *self.broker_addr)
            self._publisher.logger = self.logger
        return self._publisher

    def _multicast(self, message: dict) -> dict:
        host, port = self.coordinator_addr
        peer = f"{host}:{port}"
        with connect(host, port) as s:
            send_message(s, make_envelope("group.multicast", self.name,
                                          {"group": REPLICA_GROUP, "message": message},
                                          receiver="group-coordinator"), self.logger, peer)
            reply, _ = recv_message(s, self.logger, peer)
        return reply["payload"]

    # storage: in-memory dict, or the ring overlay when one is configured
    def _load(self, reservation_id: str) -> dict | None:
        if self._ring is None:
            return self.reservations.get(reservation_id)
        r = self._ring.get(f"reservation:{reservation_id}")
        return r["value"] if r["found"] else None

    def _save(self, res: dict) -> None:
        rid = res["reservation_id"]
        if self._ring is None:
            self.reservations[rid] = res
            return
        self._ring.put(f"reservation:{rid}", res)
        idx = self._ring.get(RES_INDEX)                      # read-modify-write: safe because bookings are
        self._ring.put(RES_INDEX, (idx["value"] if idx["found"] else []) + [rid])   # exclusive (see _exclusive)

    def list_reservations(self):
        if self._ring is None:
            return list(self.reservations.values())
        idx = self._ring.get(RES_INDEX)
        ids = idx["value"] if idx["found"] else []
        return [r for r in (self._load(i) for i in ids) if r]

    def get(self, reservation_id: str):
        r = self._load(reservation_id)
        if r is None:
            raise RPCError(404, "Reservation not found", {"reservation_id": reservation_id})
        return r

    def book(self, property_id: int, guest_name: str = "Guest", nights: int = 1):
        with self._exclusive():
            # 1) request-reply to the Property node
            avail = self._prop().call("availability.check", property_id=property_id)
            if not avail["available"]:
                return {"status": "rejected", "message": "Property is not available", "property_id": property_id}
            if self.book_delay:
                time.sleep(self.book_delay)       # simulated processing between check and update
            self._prop().call("property.set_available", property_id=property_id, available=False)
            res = {
                "reservation_id": "R-" + uuid.uuid4().hex[:8],
                "property_id": avail["property_id"],
                "property_name": avail["name"],
                "guest_name": guest_name,
                "nights": nights,
                "amount": avail["price"] * nights,
                "status": "confirmed",
                "booked_by": self.name,
                "created_at": now_iso(),
            }
            self._save(res)
        # 2) publish-subscribe: tell every interested service about the booking
        pub_ack = self._pub().publish(BOOKING_TOPIC, res)
        # 3) group communication: keep every property replica consistent
        grp_ack = self._multicast({"op": "availability_update", "property_id": res["property_id"],
                                   "available": False, "reservation_id": res["reservation_id"]})
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
