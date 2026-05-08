"""ClickHouse inserts with bounded timeouts, retries, and typed errors."""

from __future__ import annotations

import random
import time
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ingestor.settings import IngestorSettings


def create_client(settings: IngestorSettings) -> clickhouse_connect.driver.client.Client:
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=int(settings.clickhouse_port),
        username=settings.clickhouse_username,
        password=settings.clickhouse_password or None,
        database=settings.clickhouse_database,
        secure=settings.clickhouse_secure,
        connect_timeout=int(settings.clickhouse_connect_timeout_s),
        send_receive_timeout=int(settings.clickhouse_send_receive_timeout_s),
        compress=True,
    )


def _evidence_table_name(settings: IngestorSettings) -> str:
    return f"{settings.clickhouse_database}.{settings.evidence_table}"


def _anchors_table_name(settings: IngestorSettings) -> str:
    return f"{settings.clickhouse_database}.{settings.anchors_table}"


def _insert_evidence_manifest_once(
    client: clickhouse_connect.driver.client.Client,
    settings: IngestorSettings,
    row: dict[str, Any],
) -> None:
    table = _evidence_table_name(settings)
    column_names = [
        "tenant_id",
        "manifest_id",
        "engine_version",
        "timestamp_ns",
        "final_decision",
        "total_execution_time_us",
        "signals",
        "trace_json",
        "crypto_algorithm",
        "crypto_signature_hex",
        "crypto_key_id",
        "raw_manifest_sha256",
    ]
    data = [
        [
            row["tenant_id"],
            row["manifest_id"],
            row["engine_version"],
            row["timestamp_ns"],
            row["final_decision"],
            row["total_execution_time_us"],
            row["signals"],
            row["trace_json"],
            row["crypto_algorithm"],
            row["crypto_signature_hex"],
            row["crypto_key_id"],
            row["raw_manifest_sha256"],
        ]
    ]
    client.insert(table, data, column_names=column_names)


def insert_evidence_manifest(
    client: clickhouse_connect.driver.client.Client,
    settings: IngestorSettings,
    row: dict[str, Any],
) -> None:
    """Insert a single manifest row with bounded retries (default 3 for ingestor DLQ boundary)."""
    max_attempts = max(1, int(settings.clickhouse_insert_max_attempts))
    for attempt in range(max_attempts):
        try:
            _insert_evidence_manifest_once(client, settings, row)
            return
        except (ClickHouseError, TimeoutError, OSError):
            if attempt + 1 >= max_attempts:
                raise
            delay = min(8.0, 0.2 * (2**attempt))
            jitter = random.uniform(0.0, max(0.01, delay * 0.15))
            time.sleep(delay + jitter)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=0.2, max=8.0),
    retry=retry_if_exception_type((ClickHouseError, TimeoutError, OSError)),
    reraise=True,
)
def insert_audit_anchor(
    client: clickhouse_connect.driver.client.Client,
    settings: IngestorSettings,
    tenant_id: str,
    batch_seq: int,
    batch_root_hex: str,
    manifest_count: int,
    first_manifest_id: Any,
    last_manifest_id: Any,
    first_leaf_sha256_hex: str,
    last_leaf_sha256_hex: str,
) -> None:
    table = _anchors_table_name(settings)
    data = [
        [
            tenant_id,
            batch_seq,
            batch_root_hex,
            manifest_count,
            first_manifest_id,
            last_manifest_id,
            first_leaf_sha256_hex,
            last_leaf_sha256_hex,
        ]
    ]
    column_names = [
        "tenant_id",
        "batch_seq",
        "batch_root_hex",
        "manifest_count",
        "first_manifest_id",
        "last_manifest_id",
        "first_leaf_sha256_hex",
        "last_leaf_sha256_hex",
    ]
    client.insert(table, data, column_names=column_names)
