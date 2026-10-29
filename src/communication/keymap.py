"""Key/resource to peer mapping: who is responsible for a key (UNG-91).

Resources and peers share one ID space: the 2**16-slot ring from ``ring.py``.

* A resource name (for example a room listing) becomes a *key* string such as
  ``listing:101``. ``key_id(key)`` hashes it with SHA-1 onto the ring, the same
  hash peers use for their own positions (``ring_id``).
* The peer *responsible* for a key is its **successor**: the first peer whose id
  is at or after the key's id, wrapping around after 65535. So a peer owns the
  keys in (predecessor.id, own id], and a key past the last peer wraps to the
  peer with the lowest id.

These are pure functions, so the same rule is used by the lookup router
(``lookup.py``), by the Catalog publisher and by the tests.
"""
from __future__ import annotations

from .ring import RING_SIZE, between, ring_id

LISTING_PREFIX = "listing:"


def listing_key(listing_id) -> str:
    """Key under which a room listing is stored in the overlay."""
    return f"{LISTING_PREFIX}{listing_id}"


def key_id(key: str) -> int:
    """Position of a key on the ring (0 .. RING_SIZE-1)."""
    return ring_id(key)


def responsible_id(kid: int, peer_ids) -> int:
    """Id of the peer responsible for ring position ``kid``: its successor on the ring."""
    ids = sorted(set(int(i) for i in peer_ids))
    if not ids:
        raise ValueError("no peers in the ring")
    if not 0 <= kid < RING_SIZE:
        raise ValueError(f"key id {kid} outside the ring 0..{RING_SIZE - 1}")
    for pid in ids:
        if pid >= kid:
            return pid
    return ids[0]  # wrap around


def responsible_peer(key: str, peers: list[dict]) -> dict:
    """The peer dict ({"name", "id", ...}) responsible for ``key`` among ``peers``."""
    pid = responsible_id(key_id(key), [p["id"] for p in peers])
    return next(p for p in peers if p["id"] == pid)


def is_responsible(kid: int, pred_id: int, my_id: int) -> bool:
    """True if a peer at ``my_id`` with predecessor ``pred_id`` owns ring position ``kid``.

    A peer alone in the ring (pred_id == my_id) owns every key.
    """
    return pred_id == my_id or between(kid, pred_id, my_id)


def ownership_table(keys, peers: list[dict]) -> dict[str, str]:
    """{key: name of responsible peer} - handy for logs and the report."""
    return {k: responsible_peer(k, peers)["name"] for k in keys}
