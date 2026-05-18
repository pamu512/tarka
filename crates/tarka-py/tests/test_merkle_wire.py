"""rs_merkle parity for ``tarka.merkle_wire`` (proof parse + verify)."""

from __future__ import annotations

import hashlib

import pytest

from tarka.merkle_wire import (
    merkle_proof_root,
    merkle_root_rs_sha256,
    parse_proof,
    proof_verify,
)

# ``MerkleProof::to_bytes`` example from rs_merkle 1.5 ``merkle_proof.rs`` (indices ``[3, 4]``, six leaves ``a``..``f``).
_RS_MERKLE_DOC_PROOF_BYTES = bytes(
    [
        46,
        125,
        44,
        3,
        169,
        80,
        122,
        226,
        101,
        236,
        245,
        181,
        53,
        104,
        133,
        165,
        51,
        147,
        162,
        2,
        157,
        36,
        19,
        148,
        153,
        114,
        101,
        161,
        162,
        90,
        239,
        198,
        37,
        47,
        16,
        200,
        54,
        16,
        235,
        202,
        26,
        5,
        156,
        11,
        174,
        130,
        85,
        235,
        162,
        249,
        91,
        228,
        209,
        215,
        188,
        250,
        137,
        215,
        36,
        138,
        130,
        217,
        241,
        17,
        229,
        160,
        31,
        238,
        20,
        224,
        237,
        92,
        72,
        113,
        79,
        34,
        24,
        15,
        37,
        173,
        131,
        101,
        181,
        63,
        151,
        121,
        247,
        157,
        196,
        163,
        215,
        233,
        57,
        99,
        249,
        74,
    ]
)


def _leaves_sha256_preimages(parts: list[bytes]) -> list[bytes]:
    return [hashlib.sha256(p).digest() for p in parts]


def test_parse_proof_direct_hashes_order() -> None:
    hashes = parse_proof(_RS_MERKLE_DOC_PROOF_BYTES)
    assert len(hashes) == 3
    assert all(len(h) == 32 for h in hashes)
    assert b"".join(hashes) == _RS_MERKLE_DOC_PROOF_BYTES


def test_parse_proof_rejects_non_multiple_of_32() -> None:
    with pytest.raises(ValueError, match="multiple of hash size"):
        parse_proof(b"\x00" * 31)


def test_merkle_proof_root_matches_rs_merkle_doc_vector() -> None:
    leaves = _leaves_sha256_preimages([p.encode() for p in "abcdef"])
    root = merkle_root_rs_sha256(leaves)
    got = merkle_proof_root(
        _RS_MERKLE_DOC_PROOF_BYTES,
        [3, 4],
        [leaves[3], leaves[4]],
        6,
    )
    assert got == root


def test_proof_verify_single_leaf_empty_proof() -> None:
    leaf = hashlib.sha256(b"solo").digest()
    root = merkle_root_rs_sha256([leaf])
    assert proof_verify(root, leaf, b"", 0, 1) is True


def test_proof_verify_two_leaves_sibling_in_proof() -> None:
    l0 = hashlib.sha256(b"left").digest()
    l1 = hashlib.sha256(b"right").digest()
    root = merkle_root_rs_sha256([l0, l1])
    # Inclusion proof for index 0 is the sibling digest at index 1 (one layer, one helper hash).
    assert proof_verify(root, l0, l1, 0, 2) is True
    assert proof_verify(root, l1, l0, 1, 2) is True


def test_proof_verify_rejects_wrong_root() -> None:
    leaves = _leaves_sha256_preimages([p.encode() for p in "abcdef"])
    root = merkle_root_rs_sha256(leaves)
    bad_root = bytearray(root)
    bad_root[0] ^= 1
    assert proof_verify(bytes(bad_root), leaves[3], _RS_MERKLE_DOC_PROOF_BYTES, 3, 6) is False


def test_proof_verify_rejects_bad_leaf_index() -> None:
    leaf = hashlib.sha256(b"x").digest()
    root = merkle_root_rs_sha256([leaf])
    assert proof_verify(root, leaf, b"", 1, 1) is False
