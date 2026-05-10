"""Tarka ClickHouse ingestor service (EvidenceManifest sink)."""

from ingestor.enqueue import enqueue_manifest_bytes

__all__ = ["enqueue_manifest_bytes"]
