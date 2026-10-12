"""Communication layer for the CECS 327 Distributed Lodging Python simulation.

Modules:
    codec      - marshalling / unmarshalling (JSON and XML) of message envelopes
    transport  - length-prefixed framing over TCP sockets
    msglog     - ISO-8601 timestamped message logging (JSON Lines)
    rpc        - JSON-RPC 2.0 over TCP sockets (request-reply)
    broker     - publish-subscribe broker with multiple subscribers
    group      - group communication (membership + multicast)
    services   - lodging nodes (property / reservation) built on the above
    run        - command-line launcher for every node
    demo       - end-to-end demo that starts every node as its own process
"""
