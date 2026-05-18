import hashlib

from ingestor.merkle import merkle_root_sha256


def test_merkle_two_leaves() -> None:
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    root = merkle_root_sha256([a, b])
    assert len(root) == 32
    assert root == hashlib.sha256(a + b).digest()


def test_merkle_odd_duplicates_last() -> None:
    a = hashlib.sha256(b"x").digest()
    root = merkle_root_sha256([a])
    assert root == a
