"""Launch one node of the communication demo.

    python -m src.communication.run property
    python -m src.communication.run reservation
    python -m src.communication.run broker
    python -m src.communication.run coordinator
    python -m src.communication.run subscriber notification-service
    python -m src.communication.run replica replica-1 6101
"""
from __future__ import annotations

import sys
import time

from .broker import Broker, Subscriber
from .group import GroupCoordinator, GroupMember
from .msglog import MessageLogger
from .services import (BOOKING_TOPIC, PORTS, REPLICA_GROUP, SUBSCRIBERS, PropertyNode, ReservationNode,
                       replica_handler)


def _forever(server):
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()


def main(argv: list[str]) -> None:
    role = argv[0] if argv else ""
    if role == "property":
        _forever(PropertyNode())
    elif role == "reservation":
        _forever(ReservationNode())
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
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
