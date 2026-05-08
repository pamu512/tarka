"""ClickHouse evidence store DDL for the Triple-DB stack.

Applies idempotent DDL for ``tarka_audit.evidence_manifests`` using
``pulumi_command.local.Command``. The command runs this file as ``python3 … --pulumi-apply-ddl``
so statements are executed over the HTTP interface with explicit connect/read timeouts and
retries (transient network failures); ClickHouse HTTP returns non-success status codes on
statement errors when possible.

Partitioning follows the stack requirement: **MergeTree** with **month** partitions
(``toYYYYMM(event_ts)``). Column layout matches ``services/ingestor/schema/clickhouse.sql`` for
compatibility with ingestors and replay tooling. **Maximum retention** is one calendar year on
``event_ts`` (same intent as ``DELETE WHERE event_ts < now() - INTERVAL 1 YEAR``) so small teams
do not rely on manual disk cleanup.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pulumi
from pulumi_command import local

# Audit database and primary evidence table (aligned with services/ingestor/schema/clickhouse.sql).
_AUDIT_DB = "tarka_audit"
_TABLE = "evidence_manifests"

# Idempotent DDL — safe to re-apply; month-only partitions per deploy contract.
_DDL_STATEMENTS: tuple[str, ...] = (
    f"CREATE DATABASE IF NOT EXISTS {_AUDIT_DB}",
    f"""
CREATE TABLE IF NOT EXISTS {_AUDIT_DB}.{_TABLE}
(
    tenant_id LowCardinality(String),
    manifest_id UUID,
    engine_version LowCardinality(String),
    timestamp_ns UInt64,
    event_ts DateTime64(3, 'UTC') MATERIALIZED toDateTime64(timestamp_ns / 1000000000, 3, 'UTC'),
    final_decision UInt8,
    total_execution_time_us UInt64,
    signals Map(String, String),
    trace_json JSON,
    crypto_algorithm LowCardinality(String),
    crypto_signature_hex String,
    crypto_key_id String,
    raw_manifest_sha256 FixedString(32),
    under_investigation UInt8 DEFAULT 0
        COMMENT '1 = retain full manifest past 90d until max TTL (investigation / legal hold)',
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_ts)
ORDER BY (tenant_id, event_ts, manifest_id)
/* Max age 1y on event_ts (equivalent to DELETE WHERE event_ts < now() - INTERVAL 1 YEAR). */
TTL
    event_ts + INTERVAL 90 DAY DELETE WHERE under_investigation = 0,
    event_ts + INTERVAL 1 YEAR DELETE
SETTINGS index_granularity = 8192
""".strip(),
)


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else v


def _http_post_sql(
    *,
    base_url: str,
    user: str,
    password: str,
    sql: str,
    connect_timeout_s: float,
    read_timeout_s: float,
) -> None:
    """POST a single SQL statement. Raises RuntimeError on ClickHouse or HTTP errors."""
    # Single-statement POST; database may be omitted for CREATE DATABASE.
    url = f"{base_url.rstrip('/')}/?wait_end_of_query=1"
    body = sql.encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=(connect_timeout_s, read_timeout_s)) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:8192]
        raise RuntimeError(f"ClickHouse HTTP {e.code}: {detail}") from e
    except TimeoutError as e:
        raise RuntimeError("ClickHouse request timed out") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ClickHouse connection error: {e}") from e
    if not raw:
        return
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return
    # ClickHouse may surface parse errors in the body even when HTTP status is 200.
    if text.startswith("Code:") or "\nCode:\t" in text[:512]:
        raise RuntimeError(f"ClickHouse error body: {text[:4096]}")
    head = text[:1]
    if head == "{":
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and "exception" in payload:
                raise RuntimeError(f"ClickHouse exception: {payload.get('exception')}")
        except json.JSONDecodeError:
            pass


def _apply_with_retries(
    *,
    base_url: str,
    user: str,
    password: str,
    connect_timeout_s: float,
    read_timeout_s: float,
    max_attempts: int,
) -> None:
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            for stmt in _DDL_STATEMENTS:
                _http_post_sql(
                    base_url=base_url,
                    user=user,
                    password=password,
                    sql=stmt,
                    connect_timeout_s=connect_timeout_s,
                    read_timeout_s=read_timeout_s,
                )
            return
        except (RuntimeError, OSError) as e:
            last_err = e
            if attempt >= max_attempts:
                break
            # Exponential backoff with jitter (bounded).
            sleep_s = min(30.0, (2 ** (attempt - 1)) * 0.5 + random.random() * 0.25)
            print(
                f"clickhouse DDL attempt {attempt}/{max_attempts} failed: {e}; "
                f"retrying in {sleep_s:.2f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
    assert last_err is not None
    raise last_err


def _pulumi_apply_main() -> int:
    host = _env("CH_HOST", "localhost")
    port = int(_env("CH_HTTP_PORT", "8123"))
    secure = _env("CH_SECURE", "0").lower() in ("1", "true", "yes")
    user = _env("CH_USER", "default")
    password = _env("CH_PASSWORD", "")
    connect_timeout_s = float(_env("CH_CONNECT_TIMEOUT_S", "10"))
    read_timeout_s = float(_env("CH_READ_TIMEOUT_S", "120"))
    max_attempts = int(_env("CH_MAX_ATTEMPTS", "3"))
    scheme = "https" if secure else "http"
    base_url = f"{scheme}://{host}:{port}"
    try:
        _apply_with_retries(
            base_url=base_url,
            user=user,
            password=password,
            connect_timeout_s=connect_timeout_s,
            read_timeout_s=read_timeout_s,
            max_attempts=max_attempts,
        )
    except Exception as e:
        print(f"clickhouse DDL apply failed: {e}", file=sys.stderr)
        return 1
    print(f"clickhouse DDL ok: {_AUDIT_DB}.{_TABLE} (MergeTree, monthly partitions)")
    return 0


def provision(*, cfg: pulumi.Config | None = None) -> None:
    """Schedule idempotent ClickHouse DDL via a local Command."""
    cfg = cfg or pulumi.Config()
    if cfg.get_bool("clickhouseApplyDdl") is False:
        pulumi.log.info("triple-db:clickhouseApplyDdl is false; skipping ClickHouse DDL Command")
        return

    self_script = Path(__file__).resolve()
    create_cmd = f'{sys.executable} "{self_script}" --pulumi-apply-ddl'

    pw_out = cfg.get_secret("clickhousePassword")
    if pw_out is None:
        pw_out = pulumi.Output.from_input("")

    ch_env = pulumi.Output.all(
        cfg.require("clickhouseHost"),
        cfg.require_int("clickhouseHttpPort"),
        cfg.get_bool("clickhouseSecure") or False,
        cfg.get("clickhouseAdminUser") or "default",
        pw_out,
        cfg.get("clickhouseConnectTimeoutSeconds") or "10",
        cfg.get("clickhouseReadTimeoutSeconds") or "120",
        cfg.get("clickhouseDdlMaxAttempts") or "3",
    ).apply(
        lambda p: {
            "CH_HOST": str(p[0]),
            "CH_HTTP_PORT": str(int(p[1])),
            "CH_SECURE": "1" if p[2] else "0",
            "CH_USER": str(p[3]),
            "CH_PASSWORD": str(p[4]),
            "CH_CONNECT_TIMEOUT_S": str(p[5]),
            "CH_READ_TIMEOUT_S": str(p[6]),
            "CH_MAX_ATTEMPTS": str(p[7]),
        }
    )

    delete_cmd = "echo 'triple-db: ClickHouse DDL retained on destroy (no DROP TABLE).'"

    local.Command(
        "triple-db-clickhouse-evidence-ddl",
        create=create_cmd,
        delete=delete_cmd,
        environment=ch_env,
        triggers=["".join(_DDL_STATEMENTS)],
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ClickHouse Triple-DB helpers")
    p.add_argument(
        "--pulumi-apply-ddl",
        action="store_true",
        help="Apply evidence_manifests DDL (invoked by Pulumi local.Command)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.pulumi_apply_ddl:
        return _pulumi_apply_main()
    print("No action specified.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
