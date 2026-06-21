"""Tarka ClickHouse ingestor service (EvidenceManifest sink)."""

from enqueue import enqueue_manifest_bytes

__all__ = ["enqueue_manifest_bytes"]
