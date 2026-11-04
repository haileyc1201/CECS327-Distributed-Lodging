"""Launch one node of the communication demo.

    python -m src.communication.run property [--ring 6301,6302,...]
    python -m src.communication.run reservation [--ring 6301,6302,...]
    python -m src.communication.run broker
    python -m src.communication.run coordinator
    python -m src.communication.run subscriber notification-service
    python -m src.communication.run replica replica-1 6101
    python -m src.communication.run ring ring-A 6301            # first ring peer
    python -m src.communication.run ring ring-B 6302 6301       # joins via the peer on 6301

``property --ring`` and ``reservation --ring`` store their records in the ring overlay
(the listed ports are bootstrap peers) instead of in memory.
"""
from __future__ import annotations

import sys
import time

from .broker import Broker, Subscriber
from .group import GroupCoordinator, GroupMember
from .msglog import MessageLogger
from .ring import RingClient, RingNode
from .services import (BOOKING_TOPIC, PORTS, REPLICA_GROUP, SUBSCRIBERS, PropertyNode, ReservationNode,
                       replica_handler)


def _forever(server):
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()


def _ring_client(name: str, argv: list[str]) -> RingClient | None:
    """Build a RingClient from ``--ring p1,p2,...`` if present."""
    if len(argv) > 2 and argv[1] == "--ring":
        return RingClient(name, [("127.0.0.1", int(p)) for p in argv[2].split(",")])
    return None


def main(argv: list[str]) -> None:
    role = argv[0] if argv else ""
    if role == "property":
        _forever(PropertyNode(ring=_ring_client("property-rpc", argv)))
    elif role == "reservation":
        _forever(ReservationNode(ring=_ring_client("reservation-rpc", argv)))
    elif role == "broker":
        _forever(Broker(port=PORTS["broker"]))
    elif role == "coordinator":
        _forever(GroupCoordinator(port=PORTS["coordinator"]))
    elif role == "subscriber":
        name = argv[1]
        log = MessageLogger(name)
        template = SUBSCRIBERS.get(name, "received {reservation_id}")
        sub = Subscriber(name, "127.0.0.1", PORTS["broker"], [BOOKING_TOPIC],
                         handler=lambda p: log.info(template.format(**p["event"])))
        sub.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sub.close()
    elif role == "replica":
        name, port = argv[1], int(argv[2])
        member = GroupMember(name, REPLICA_GROUP, "127.0.0.1", PORTS["coordinator"], port=port,
                             on_message=lambda m, msg: (replica_handler(m, msg),
                                                        m.logger.info(f"replica state now {m.state}")))
        member.start()
        member.join()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            member.leave()
            member.stop()
    elif role == "ring":
        name, port = argv[1], int(argv[2])
        node = RingNode(name, port=port).start()
        if len(argv) > 3:
            node.join("127.0.0.1", int(argv[3]))
        try:
            while not node._stop.is_set():          # stops after a ring.leave request
                time.sleep(1)
                node.stabilize()                    # heartbeat: ping successor, repair if it crashed
        except KeyboardInterrupt:
            node.leave()
            node.stop()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])