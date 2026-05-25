#!/usr/bin/env python3
"""
Data Lifecycle Manager: tier evidence older than N days from ClickHouse to S3 (Standard-IA) as Parquet.

- Reads `evidence_manifests` (and correlated `audit_anchors`) via clickhouse-connect.
- Builds Polars DataFrames for fast columnar conversion; writes Parquet with ZSTD via PyArrow.
- Embeds Merkle batch anchors (full JSON payload) and signature column hints in **Parquet schema metadata**
  so each object remains auditable without a sidecar (subject to PyArrow footer size — very large anchor
  histories may require splitting runs).
- Uploads with boto3 using STANDARD_IA; retries with bounded exponential backoff on transient errors.

Environment (typical):
  CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD,
  CLICKHOUSE_DATABASE
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION / AWS_DEFAULT_REGION
  COLD_TIER_S3_BUCKET — required unless passed via --s3-bucket

Example:
  pip install -r scripts/data_lifecycle/requirements-cold-tier.txt
  python scripts/data_lifecycle/cold_tier_evidence_to_s3.py \\
    --s3-bucket my-audit-archive \\
    --s3-prefix cold-tier/evidence \\
    --dry-run

Operational notes:
  - Row-level Ed25519 / prehash material lives in columns `crypto_algorithm`, `crypto_signature_hex`,
    `crypto_key_id`, `raw_manifest_sha256`.
  - Batch Merkle roots live in `audit_anchors`; exported rows include anchors with `anchored_at` before
    the same cutoff so historical roots remain inspectable alongside evidence rows.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import clickhouse_connect
import polars as pl
import pyarrow.parquet as pq
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

METADATA_MAX_BYTES = 3_500_000
DEFAULT_RETENTION_DAYS = 90
DEFAULT_BATCH_ROWS = 50_000


def _utc_cutoff(retention_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


def _validate_identifier(name: str, label: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise ValueError(f"invalid {label} identifier {name!r}")
    return name


def _normalize_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested CH types for stable Parquet (Maps / JSON → UTF-8 JSON strings)."""
    out = dict(row)
    sig = out.get("signals")
    if isinstance(sig, dict):
        out["signals_json"] = json.dumps(sig, separators=(",", ":"), sort_keys=True)
        del out["signals"]
    elif sig is not None:
        out["signals_json"] = json.dumps(sig, default=str)
        del out["signals"]
    else:
        out["signals_json"] = "{}"

    tj = out.get("trace_json")
    if tj is not None and not isinstance(tj, str):
        out["trace_json"] = json.dumps(tj, separators=(",", ":"), default=str)
    elif tj is None:
        out["trace_json"] = "[]"

    mid = out.get("manifest_id")
    out["manifest_id"] = str(mid) if mid is not None else ""

    raw_sha = out.get("raw_manifest_sha256")
    if isinstance(raw_sha, (bytes, memoryview, bytearray)):
        out["raw_manifest_sha256_hex"] = bytes(raw_sha).hex()
        del out["raw_manifest_sha256"]
    else:
        out["raw_manifest_sha256_hex"] = str(raw_sha or "")

    ing = out.get("ingested_at")
    if ing is not None and not isinstance(ing, str):
        out["ingested_at"] = ing.isoformat() if hasattr(ing, "isoformat") else str(ing)
    return out


def _ch_client(args: argparse.Namespace) -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=args.clickhouse_host,
        port=int(args.clickhouse_port),
        username=args.clickhouse_user,
        password=args.clickhouse_password or None,
        database=args.clickhouse_database,
        secure=bool(args.clickhouse_secure),
        connect_timeout=int(args.connect_timeout_s),
        send_receive_timeout=int(args.send_receive_timeout_s),
        compress=True,
    )


def _tenant_and_clause(tenant_id: str | None) -> str:
    """Append-only SQL fragment: `` AND tenant_id = '…'`` when a tenant scope is set."""
    if tenant_id is None:
        return ""
    tid = tenant_id.strip()
    if not tid:
        return ""
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", tid):
        raise ValueError(f"invalid tenant_id for SQL predicate: {tenant_id!r}")
    esc = tid.replace("'", "''")
    return f" AND tenant_id = '{esc}'"


def fetch_evidence_batch(
    client: clickhouse_connect.driver.Client,
    *,
    database: str,
    table: str,
    cutoff: datetime,
    limit: int,
    offset: int,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    db = _validate_identifier(database, "database")
    tbl = _validate_identifier(table, "table")
    cutoff_sql = cutoff.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tenant_clause = _tenant_and_clause(tenant_id)
    q = f"""
    SELECT
        tenant_id,
        manifest_id,
        engine_version,
        timestamp_ns,
        final_decision,
        total_execution_time_us,
        signals,
        trace_json,
        crypto_algorithm,
        crypto_signature_hex,
        crypto_key_id,
        raw_manifest_sha256,
        ingested_at
    FROM {db}.{tbl}
    WHERE ingested_at < toDateTime64('{cutoff_sql}', 3, 'UTC') {tenant_clause}
    ORDER BY ingested_at, manifest_id
    LIMIT {int(limit)} OFFSET {int(offset)}
    """
    result = client.query(q)
    return list(result.named_results())


def fetch_audit_anchors(
    client: clickhouse_connect.driver.Client,
    *,
    database: str,
    table: str,
    cutoff: datetime,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Batch Merkle anchors anchored before cutoff (same retention window as evidence export)."""
    db = _validate_identifier(database, "database")
    tbl = _validate_identifier(table, "table")
    cutoff_sql = cutoff.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tenant_clause = _tenant_and_clause(tenant_id)
    q = f"""
    SELECT
        tenant_id,
        batch_seq,
        batch_root_hex,
        manifest_count,
        first_manifest_id,
        last_manifest_id,
        first_leaf_sha256_hex,
        last_leaf_sha256_hex,
        anchored_at
    FROM {db}.{tbl}
    WHERE anchored_at < toDateTime64('{cutoff_sql}', 3, 'UTC') {tenant_clause}
    ORDER BY batch_seq
    """
    result = client.query(q)
    return list(result.named_results())


def _pa_metadata_bytes(meta: dict[str, str]) -> dict[bytes, bytes]:
    return {k.encode("utf-8"): v.encode("utf-8") for k, v in meta.items()}


def evidence_to_parquet_bytes(
    rows: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    *,
    cutoff_iso: str,
    part_label: str,
) -> bytes:
    normalized = [_normalize_evidence_row(r) for r in rows]
    if not normalized:
        raise ValueError("empty evidence batch")
    df = pl.from_dicts(normalized)
    table = df.to_arrow()

    anchors_json = json.dumps(anchors, separators=(",", ":"), default=str)
    if len(anchors_json.encode("utf-8")) > METADATA_MAX_BYTES:
        raise RuntimeError(
            "audit_anchors JSON exceeds safe Parquet metadata budget; "
            "reduce retention window or export anchors in a separate job."
        )

    meta_str = _pa_metadata_bytes(
        {
            "tarka.cold_tier_version": "1",
            "tarka.cold_tier_cutoff_utc": cutoff_iso,
            "tarka.export_part": part_label,
            "tarka.merkle_anchors_json": anchors_json,
            "tarka.merkle_note": (
                "Batch Merkle roots (batch_seq, batch_root_hex, leaf bounds) for anchors "
                "with anchored_at before cutoff; joins to evidence are operational (batch_seq order)."
            ),
            "tarka.signature_columns": json.dumps(
                [
                    "crypto_algorithm",
                    "crypto_signature_hex",
                    "crypto_key_id",
                    "raw_manifest_sha256_hex",
                ]
            ),
            "tarka.signature_note": (
                "Row-level cryptographic material preserved in named columns; raw SHA-256 of manifest "
                "bytes is exported as raw_manifest_sha256_hex (64-char hex)."
            ),
        }
    )
    merged: dict[bytes, bytes] = dict(table.schema.metadata or {})
    merged.update(meta_str)
    table = table.replace_schema_metadata(merged)

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def _upload_with_retries(
    s3: Any,
    *,
    bucket: str,
    key: str,
    body: bytes,
    storage_class: str,
    max_attempts: int,
    base_delay_s: float,
    max_delay_s: float,
) -> None:
    attempt = 0
    last_exc: BaseException | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                StorageClass=storage_class,
            )
            return
        except ClientError as exc:
            last_exc = exc
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"AccessDenied", "NoSuchBucket", "InvalidAccessKeyId"}:
                raise
        except TimeoutError as exc:
            last_exc = exc
        except OSError as exc:
            last_exc = exc
        delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, delay * 0.2)
        logger.warning(
            "S3 upload attempt %s/%s failed: %s; sleeping %.2fs",
            attempt,
            max_attempts,
            last_exc,
            delay + jitter,
        )
        time.sleep(delay + jitter)
    raise RuntimeError(f"S3 upload exhausted retries for s3://{bucket}/{key}") from last_exc


def purge_manifest_ids(
    client: clickhouse_connect.driver.Client,
    *,
    database: str,
    table: str,
    ids: list[str],
    tenant_id: str | None = None,
) -> None:
    """Lightweight delete for exported UUIDs (ClickHouse may apply asynchronously)."""
    if not ids:
        return
    db = _validate_identifier(database, "database")
    tbl = _validate_identifier(table, "table")
    chunk_size = 500
    uuid_re = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    )
    tenant_extra = ""
    if tenant_id is not None:
        safe_tenant = _validate_identifier(tenant_id, "tenant_id")
        tenant_extra = f" AND tenant_id = '{safe_tenant}'"
    for i in range(0, len(ids), chunk_size):
        part = ids[i : i + chunk_size]
        for u in part:
            if not uuid_re.fullmatch(u):
                raise ValueError(f"refusing purge: invalid manifest_id {u!r}")
        tpl = ", ".join(f"'{u}'" for u in part)
        sql = f"ALTER TABLE {db}.{tbl} DELETE WHERE manifest_id IN ({tpl}){tenant_extra}"
        client.command(sql)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS, ge=1, le=3650)
    p.add_argument("--batch-rows", type=int, default=DEFAULT_BATCH_ROWS, ge=100, le=5_000_000)
    p.add_argument("--clickhouse-host", default=None, help="Default CLICKHOUSE_HOST or 127.0.0.1")
    p.add_argument("--clickhouse-port", type=int, default=None)
    p.add_argument("--clickhouse-user", default=None)
    p.add_argument("--clickhouse-password", default=None)
    p.add_argument("--clickhouse-database", default=None)
    p.add_argument("--clickhouse-secure", action="store_true", help="Use HTTPS interface")
    p.add_argument("--evidence-table", default="evidence_manifests")
    p.add_argument("--anchors-table", default="audit_anchors")
    p.add_argument(
        "--tenant-id",
        default=None,
        help="Restrict export/purge to this tenant_id (same slug as TARKA_INGESTOR_TENANT_ID)",
    )
    p.add_argument("--connect-timeout-s", type=float, default=15.0)
    p.add_argument("--send-receive-timeout-s", type=float, default=120.0)
    p.add_argument("--s3-bucket", default=None, help="Or env COLD_TIER_S3_BUCKET")
    p.add_argument("--s3-prefix", default="cold-tier/evidence", help="Key prefix without leading slash")
    p.add_argument("--s3-endpoint-url", default=None, help="For MinIO / custom S3-compatible endpoints")
    p.add_argument(
        "--storage-class",
        default="STANDARD_IA",
        help="S3 storage class (e.g. STANDARD_IA, INTELLIGENT_TIERING)",
    )
    p.add_argument("--upload-max-attempts", type=int, default=6, ge=1, le=30)
    p.add_argument("--upload-base-delay-s", type=float, default=0.5)
    p.add_argument("--upload-max-delay-s", type=float, default=30.0)
    p.add_argument(
        "--purge-clickhouse",
        action="store_true",
        help="Issue ALTER DELETE for exported manifest_ids after successful upload",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and build Parquet bytes but skip S3 upload and purge",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    import os

    host = args.clickhouse_host or os.environ.get("CLICKHOUSE_HOST", "127.0.0.1")
    port = args.clickhouse_port if args.clickhouse_port is not None else int(
        os.environ.get("CLICKHOUSE_PORT", "8123"),
    )
    user = args.clickhouse_user or os.environ.get("CLICKHOUSE_USER", "default")
    password = args.clickhouse_password if args.clickhouse_password is not None else os.environ.get(
        "CLICKHOUSE_PASSWORD",
        "",
    )
    database = args.clickhouse_database or os.environ.get("CLICKHOUSE_DATABASE", "tarka_audit")
    bucket = args.s3_bucket or os.environ.get("COLD_TIER_S3_BUCKET")
    if not bucket and not args.dry_run:
        logger.error("S3 bucket required (pass --s3-bucket or set COLD_TIER_S3_BUCKET)")
        return 2

    args.clickhouse_host = host
    args.clickhouse_port = port
    args.clickhouse_user = user
    args.clickhouse_password = password
    args.clickhouse_database = database
    if args.s3_bucket is None:
        args.s3_bucket = bucket

    cutoff = _utc_cutoff(args.retention_days)
    cutoff_iso = cutoff.isoformat()

    client = _ch_client(args)
    boto_cfg = BotoConfig(
        connect_timeout=10,
        read_timeout=120,
        retries={"max_attempts": 10, "mode": "adaptive"},
    )
    session = boto3.session.Session()
    s3 = session.client("s3", config=boto_cfg, endpoint_url=args.s3_endpoint_url)

    logger.info("Retention cutoff (UTC): %s (%s days)", cutoff_iso, args.retention_days)

    anchors = fetch_audit_anchors(
        client,
        database=args.clickhouse_database,
        table=args.anchors_table,
        cutoff=cutoff,
    )
    logger.info("Loaded %s audit anchor rows for metadata embedding", len(anchors))

    offset = 0
    total_exported = 0
    while True:
        rows = fetch_evidence_batch(
            client,
            database=args.clickhouse_database,
            table=args.evidence_table,
            cutoff=cutoff,
            limit=args.batch_rows,
            offset=offset,
            tenant_id=args.tenant_id,
        )
        if not rows:
            break

        part_id = uuid.uuid4().hex[:12]
        part_label = f"{cutoff.strftime('%Y%m%d')}_{part_id}"
        key = (
            f"{args.s3_prefix.strip('/')}/year={cutoff.year}/month={cutoff.month:02d}/"
            f"day={cutoff.day:02d}/evidence_part_{part_label}.parquet"
        )

        parquet_bytes = evidence_to_parquet_bytes(
            rows,
            anchors,
            cutoff_iso=cutoff_iso,
            part_label=part_label,
        )
        logger.info(
            "Prepared part %s rows=%s parquet_bytes=%s key=%s",
            part_label,
            len(rows),
            len(parquet_bytes),
            key,
        )

        if not args.dry_run and args.s3_bucket:
            _upload_with_retries(
                s3,
                bucket=args.s3_bucket,
                key=key,
                body=parquet_bytes,
                storage_class=args.storage_class,
                max_attempts=args.upload_max_attempts,
                base_delay_s=args.upload_base_delay_s,
                max_delay_s=args.upload_max_delay_s,
            )
            logger.info("Uploaded s3://%s/%s (%s)", args.s3_bucket, key, args.storage_class)

            if args.purge_clickhouse:
                ids = [str(r["manifest_id"]) for r in rows]
                purge_manifest_ids(
                    client,
                    database=args.clickhouse_database,
                    table=args.evidence_table,
                    ids=ids,
                    tenant_id=args.tenant_id,
                )
                logger.info("Submitted ClickHouse DELETE for %s manifest_ids", len(ids))

        total_exported += len(rows)
        offset += len(rows)
        if len(rows) < args.batch_rows:
            break

    logger.info("Finished cold-tier export; evidence_rows_processed=%s", total_exported)
    if total_exported == 0:
        logger.info("No rows older than cutoff — nothing to export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
