"""
rs_merkle (1.5) SHA-256 Merkle tree matching ``tarka_core::evidence::merkle``.

Vendored from ``services/tarka-verifier`` so ``tarka-py`` stays self-contained.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

# rs_merkle ``algorithms::Sha256`` hash width (``Hasher::hash_size``).
_HASH_SIZE: Final[int] = 32


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


def _difference_preserve_order(a: list[int], b: list[int]) -> list[int]:
    """``utils::collections::difference`` — elements in *a* not in *b*, order of *a* preserved."""
    bset = set(b)
    return [x for x in a if x not in bset]


def proof_indices_by_layers(
    sorted_leaf_indices: list[int], leaves_count: int
) -> list[list[int]]:
    """
    Layered helper-node indices for inclusion proofs.

    Matches ``rs_merkle::utils::indices::proof_indices_by_layers`` (rs_merkle 1.5).
    """
    depth = tree_depth(leaves_count)
    uneven = uneven_layers(leaves_count)
    layer_nodes = list(sorted_leaf_indices)
    proof_indices: list[list[int]] = []
    for layer_index in range(depth):
        sibs = sibling_indices(layer_nodes)
        if (leaves_count_uneven := uneven.get(layer_index)) is not None and layer_nodes:
            if layer_nodes[-1] == leaves_count_uneven - 1:
                sibs = sibs[:-1]
        proof_nodes_indices = _difference_preserve_order(sibs, layer_nodes)
        proof_indices.append(proof_nodes_indices)
        layer_nodes = parent_indices(layer_nodes)
    return proof_indices


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


def parse_proof(proof_bytes: bytes) -> list[bytes]:
    """
    Deserialize ``MerkleProof::from_bytes`` / ``DirectHashesOrder`` wire format.

    Proof hashes are concatenated left-to-right, bottom-to-top (same order as
    ``MerkleProof::to_bytes`` in rs_merkle 1.5).
    """
    if len(proof_bytes) % _HASH_SIZE != 0:
        raise ValueError(
            f"proof bytes length {len(proof_bytes)} is not a multiple of hash size {_HASH_SIZE}"
        )
    out: list[bytes] = []
    for i in range(0, len(proof_bytes), _HASH_SIZE):
        out.append(proof_bytes[i : i + _HASH_SIZE])
    return out


def merkle_proof_root(
    proof_bytes: bytes,
    leaf_indices: list[int],
    leaf_hashes: list[bytes],
    total_leaves_count: int,
) -> bytes:
    """
    Recompute the Merkle root from helper hashes and known leaves.

    Semantically equivalent to ``rs_merkle::MerkleProof::root`` for ``Sha256`` /
    ``DirectHashesOrder`` proofs.
    """
    if len(leaf_indices) != len(leaf_hashes):
        raise ValueError("leaf_indices and leaf_hashes length mismatch")
    proof_hashes = parse_proof(proof_bytes)
    for lh in leaf_hashes:
        if len(lh) != _HASH_SIZE:
            raise ValueError("leaf hashes must be 32 bytes")

    leaf_tuples: list[tuple[int, bytes]] = sorted(
        zip(leaf_indices, leaf_hashes), key=lambda x: x[0]
    )
    sorted_indices = [t[0] for t in leaf_tuples]

    bins = proof_indices_by_layers(sorted_indices, total_leaves_count)
    proof_copy = list(proof_hashes)
    proof_layers: list[list[tuple[int, bytes]]] = []
    for proof_idx_layer in bins:
        if len(proof_copy) < len(proof_idx_layer):
            raise ValueError("not enough hashes to calculate Merkle root from proof")
        chunk = [proof_copy.pop(0) for _ in range(len(proof_idx_layer))]
        proof_layers.append(list(zip(proof_idx_layer, chunk)))

    if proof_layers:
        proof_layers[0].extend(leaf_tuples)
        proof_layers[0].sort(key=lambda x: x[0])
    else:
        proof_layers.append(leaf_tuples)

    td = tree_depth(total_leaves_count)
    layers = _build_tree_inner(proof_layers, td)
    root_layer = layers[-1]
    if len(root_layer) != 1:
        raise RuntimeError("could not derive single root from proof")
    return root_layer[0][1]


def proof_verify(
    expected_merkle_root: bytes,
    leaf_hash: bytes,
    proof_bytes: bytes,
    leaf_index: int,
    total_leaves: int,
) -> bool:
    """
    Verify a rs_merkle ``DirectHashesOrder`` inclusion proof for **one** leaf.

    This mirrors ``MerkleProof::<Sha256>::verify(root, &[leaf_index], &[leaf_hash], total_leaves)``.
    You must supply ``leaf_index`` and ``total_leaves``; they are not recoverable from the other
    arguments alone.

    Returns ``False`` on any decoding, arity, or root mismatch (same broad behavior as the Rust API).
    """
    if len(expected_merkle_root) != _HASH_SIZE:
        return False
    if len(leaf_hash) != _HASH_SIZE:
        return False
    if leaf_index < 0 or total_leaves < 0:
        return False
    if total_leaves == 0:
        return False
    if leaf_index >= total_leaves:
        return False
    try:
        got = merkle_proof_root(
            proof_bytes, [leaf_index], [leaf_hash], total_leaves
        )
    except (ValueError, RuntimeError):
        return False
    return secrets.compare_digest(got, expected_merkle_root)


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
