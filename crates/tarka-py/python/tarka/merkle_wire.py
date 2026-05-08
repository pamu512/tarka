"""
rs_merkle (1.5) SHA-256 Merkle tree matching ``tarka_core::evidence::merkle``.

Vendored from ``services/tarka-verifier`` so ``tarka-py`` stays self-contained.
"""

from __future__ import annotations

import hashlib


def _u64_leading_zeros(n: int) -> int:
    if n == 0:
        return 64
    return 64 - n.bit_length()


def tree_depth(leaves_count: int) -> int:
    if leaves_count == 0:
        return 0
    return 8 * 8 - _u64_leading_zeros(leaves_count)


def div_ceil(x: int, y: int) -> int:
    return x // y + (1 if x % y else 0)


def uneven_layers(tree_leaves_count: int) -> dict[int, int]:
    leaves_count = tree_leaves_count
    depth = tree_depth(tree_leaves_count)
    out: dict[int, int] = {}
    for index in range(depth):
        if leaves_count % 2 != 0:
            out[index] = leaves_count
        leaves_count = div_ceil(leaves_count, 2)
    return out


def is_left_index(index: int) -> bool:
    return index % 2 == 0


def get_sibling_index(index: int) -> int:
    if is_left_index(index):
        return index + 1
    return index - 1


def sibling_indices(indices: list[int]) -> list[int]:
    return [get_sibling_index(i) for i in indices]


def parent_index(index: int) -> int:
    if is_left_index(index):
        return index // 2
    return get_sibling_index(index) // 2


def parent_indices(indices: list[int]) -> list[int]:
    parents = [parent_index(i) for i in indices]
    out: list[int] = []
    for p in parents:
        if not out or out[-1] != p:
            out.append(p)
    return out


def concat_and_hash(left: bytes, right: bytes | None) -> bytes:
    if right is None:
        return left
    if len(left) != 32 or len(right) != 32:
        raise ValueError("internal: hash size must be 32 bytes")
    return hashlib.sha256(left + right).digest()


def _build_tree_inner(
    partial_layers: list[list[tuple[int, bytes]]], full_tree_depth: int
) -> list[list[tuple[int, bytes]]]:
    partial_tree: list[list[tuple[int, bytes]]] = []
    current_layer: list[tuple[int, bytes]] = []
    reversed_layers = list(reversed(partial_layers))
    for _ in range(full_tree_depth):
        if reversed_layers:
            current_layer.extend(reversed_layers.pop())
        current_layer.sort(key=lambda t: t[0])
        partial_tree.append(list(current_layer))
        indices = [t[0] for t in current_layer]
        nodes = [t[1] for t in current_layer]
        current_layer = []
        parents = parent_indices(indices)
        for i, parent_node_index in enumerate(parents):
            left = nodes[i * 2]
            right = nodes[i * 2 + 1] if i * 2 + 1 < len(nodes) else None
            h = concat_and_hash(left, right)
            current_layer.append((parent_node_index, h))
    partial_tree.append(list(current_layer))
    return partial_tree


def merkle_root_rs_sha256(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise ValueError("leaves must be non-empty")
    for lf in leaves:
        if len(lf) != 32:
            raise ValueError("each leaf digest must be 32 bytes")
    leaf_tuples = list(enumerate(leaves))
    layers = _build_tree_inner([leaf_tuples], tree_depth(len(leaves)))
    root_layer = layers[-1]
    if len(root_layer) != 1:
        raise RuntimeError("internal: merkle root layer malformed")
    return root_layer[0][1]
