"""Binary Merkle root over fixed-size leaf digests (SHA-256, 32 bytes each)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def merkle_root_sha256(leaves: Sequence[bytes]) -> bytes:
    """Return 32-byte Merkle root. Leaves must each be 32 bytes (typically SHA-256 outputs).

    For an odd number of nodes at a level, the last node is duplicated (Bitcoin-style).
    """
    if not leaves:
        raise ValueError("merkle_root_sha256 requires at least one leaf")
    for leaf in leaves:
        if len(leaf) != 32:
            raise ValueError("each leaf must be 32 bytes")

    level: list[bytes] = list(leaves)
    while len(level) > 1:
        nxt: list[bytes] = []
        i = 0
        while i < len(level):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(hashlib.sha256(left + right).digest())
            i += 2
        level = nxt
    return level[0]
