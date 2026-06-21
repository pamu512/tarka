"""SHA-256 pin for the wire ``EvidenceManifest`` protobuf descriptor set (startup drift gate)."""

from __future__ import annotations

import hashlib

from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet


def manifest_descriptor_set_bytes() -> bytes:
    """
    Deterministic ``google.protobuf.FileDescriptorSet`` bytes for ``EvidenceManifest`` and its
    transitive imports (sorted by ``google.protobuf.FileDescriptor.name``).
    """
    from tarka.evidence.wire.v1 import evidence_pb2

    root = evidence_pb2.EvidenceManifest.DESCRIPTOR.file
    stack: list = [root]
    seen: set[str] = set()
    files: list = []
    while stack:
        fd = stack.pop()
        if fd.name in seen:
            continue
        seen.add(fd.name)
        for dep in fd.dependencies:
            stack.append(dep)
        files.append(fd)

    files.sort(key=lambda f: f.name)
    fds = FileDescriptorSet()
    for fd in files:
        proto = FileDescriptorProto()
        fd.CopyToProto(proto)
        fds.file.append(proto)
    return fds.SerializeToString()


def manifest_descriptor_set_sha256() -> str:
    """Lowercase hex SHA-256 of :func:`manifest_descriptor_set_bytes`."""
    return hashlib.sha256(manifest_descriptor_set_bytes()).hexdigest()


MANIFEST_DESCRIPTOR_SET_SHA256: str = manifest_descriptor_set_sha256()
