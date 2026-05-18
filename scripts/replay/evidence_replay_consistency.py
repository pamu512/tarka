#!/usr/bin/env python3
"""Evidence replay consistency check (cron-friendly).

Samples random ``evidence_manifests`` rows from the last N hours, re-runs each
through the Rust ``tarka replay`` CLI (ClickHouse fetch + registry rule +
deterministic engine), and detects **Engine Drift** when the replayed boolean
decision differs from the stored audit decision.

Exit codes
----------
* ``0`` — no decision drift observed (all replays completed; see JSON on stdout).
* ``1`` — **Engine Drift**: at least one manifest shows decision mismatch; if
  ``ENGINE_DRIFT_LOCK_PATH`` is set, a lock payload is written atomically.
* ``2`` — operational failure (ClickHouse unavailable after retries, bad query,
  ``tarka`` binary missing, subprocess failures, etc.).
* ``3`` — **strict sample count** not met (``--strict-sample-count``): fewer rows
  than ``--sample-size`` in the time window.

Environment (inherited by subprocess unless overridden)
-------------------------------------------------------
Mirrors ``tarka-cli`` / ``ReplayArgs``: ``CLICKHOUSE_HTTP_URL``,
``CLICKHOUSE_DATABASE``, ``CLICKHOUSE_TABLE``, ``CLICKHOUSE_USER``,
``CLICKHOUSE_PASSWORD``, ``CLICKHOUSE_ROW_POLICY_TENANT_ID``,
``TARKA_REGISTRY_URL``, ``TARKA_RULE_CONTENT_ID``, ``TARKA_TRACE_ID``, etc.

Cron example (wrap as one line in crontab)::

    0 */6 * * * ENGINE_DRIFT_LOCK_PATH=/var/lib/tarka/engine_drift.json
      TARKA_REGISTRY_URL=https://registry.internal
      /path/to/uv run python /path/to/repo/scripts/replay/evidence_replay_consistency.py
      >>/var/log/tarka/replay_consistency.log 2>&1

Rule deployment gates should treat exit code ``1`` (and the lock file when
used) as **fail closed**: block promotions until drift is investigated. Use
``--clear-lock-on-success`` to remove the lock file after a clean run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

DECISION_MISMATCH_MARKER = (
    "*** DISCREPANCY: decision mismatch (audit replay divergence) ***"
)
# Emitted under ``--strict-timing`` when execution time differs.
STRICT_TIMING_DISCREPANCY = "*** DISCREPANCY: timing differs under --strict-timing ***"
# Step-level divergence (``format_diff_report``); not prefixed with DISCREPANCY.
TRACE_DIVERGENCE_MARKERS = (
    "*** MISMATCH ***",
    "*** missing in replay ***",
    "*** extra in replay ***",
)

logger = logging.getLogger("evidence_replay_consistency")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def _validate_sql_identifier(value: str, context: str) -> None:
    if value and all(c.isascii() and (c.isalnum() or c == "_") for c in value):
        return
    raise ValueError(f"invalid SQL identifier for {context}: {value!r}")


def _clickhouse_http_url(base: str) -> None:
    parsed = urlparse(base)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return
    raise ValueError(f"CLICKHOUSE_HTTP_URL must be http(s) with host: {base!r}")


@dataclass
class ReplayOutcome:
    manifest_id: str
    returncode: int | None
    decision_mismatch: bool
    strict_timing_discrepancy: bool
    trace_divergence: bool
    stderr_tail: str
    stdout_tail: str
    duration_secs: float


@dataclass
class RunSummary:
    sampled_manifest_ids: list[str] = field(default_factory=list)
    outcomes: list[ReplayOutcome] = field(default_factory=list)
    engine_drift: bool = False
    errors: list[str] = field(default_factory=list)


def _ch_post_query(
    client: httpx.Client,
    base_url: str,
    database: str,
    user: str,
    password: str,
    row_policy_tenant_id: str | None,
    query: str,
    timeout: httpx.Timeout,
    max_retries: int,
) -> str:
    _validate_sql_identifier(database, "database")
    base = base_url.rstrip("/") + "/"
    params: dict[str, str] = {"database": database}
    if row_policy_tenant_id:
        params["tarka_tenant_id"] = row_policy_tenant_id
    url = f"{base}?{urlencode(params)}"
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            base_ms = 200 * (2 ** (attempt - 1))
            jitter = (attempt * 17) % 100
            time.sleep((base_ms + jitter) / 1000.0)
        try:
            resp = client.post(
                url,
                content=query.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                auth=(user, password or ""),
                timeout=timeout,
            )
        except httpx.TimeoutException as e:
            last_err = e
            logger.warning("ClickHouse request timeout attempt=%s", attempt)
            continue
        except httpx.TransportError as e:
            last_err = e
            logger.warning("ClickHouse transport error attempt=%s err=%s", attempt, e)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            snippet = (resp.text or "")[:512]
            last_err = RuntimeError(f"HTTP {resp.status_code}: {snippet}")
            logger.warning(
                "ClickHouse retryable status=%s attempt=%s", resp.status_code, attempt
            )
            if attempt >= max_retries:
                raise last_err
            continue

        if not resp.is_success:
            snippet = (resp.text or "")[:512]
            raise RuntimeError(f"ClickHouse HTTP {resp.status_code}: {snippet}")

        return resp.text

    assert last_err is not None
    raise last_err


def _fetch_random_manifest_ids(
    *,
    clickhouse_url: str,
    database: str,
    table: str,
    user: str,
    password: str,
    row_policy_tenant_id: str | None,
    hours: int,
    sample_size: int,
    connect_timeout: float,
    query_timeout: float,
    max_retries: int,
) -> list[str]:
    _validate_sql_identifier(database, "database")
    _validate_sql_identifier(table, "table")
    if hours < 1 or hours > 168:
        raise ValueError("hours must be in 1..168")
    if sample_size < 1 or sample_size > 500:
        raise ValueError("sample_size must be in 1..500")

    q = (
        f"SELECT manifest_id FROM `{database}`.`{table}` "
        f"WHERE event_ts >= now64(3) - toIntervalHour({hours}) "
        f"ORDER BY rand() LIMIT {sample_size} FORMAT JSONEachRow"
    )
    timeout = httpx.Timeout(query_timeout, connect=connect_timeout)
    with httpx.Client() as client:
        body = _ch_post_query(
            client,
            clickhouse_url,
            database,
            user,
            password,
            row_policy_tenant_id,
            q,
            timeout,
            max_retries,
        )

    ids: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JSONEachRow parse failed: {e}; line={line[:200]}") from e
        mid = row.get("manifest_id")
        if mid is None:
            raise RuntimeError(f"missing manifest_id in row: {line[:200]}")
        ids.append(str(mid))
    return ids


def _tail(s: str, max_len: int = 1200) -> str:
    if len(s) <= max_len:
        return s
    return "…" + s[-max_len:]


def _run_tarka_replay(
    *,
    tarka_binary: str,
    manifest_id: str,
    replay_timeout_secs: float,
    extra_env: dict[str, str],
    passthrough_args: list[str],
) -> ReplayOutcome:
    cmd = [tarka_binary, "replay", manifest_id, *passthrough_args]
    env = os.environ.copy()
    env.update(extra_env)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=replay_timeout_secs,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        dur = time.perf_counter() - t0
        err = (e.stderr or "") if hasattr(e, "stderr") else ""
        out = (e.stdout or "") if hasattr(e, "stdout") else ""
        return ReplayOutcome(
            manifest_id=manifest_id,
            returncode=None,
            decision_mismatch=False,
            strict_timing_discrepancy=False,
            trace_divergence=False,
            stderr_tail=_tail(f"subprocess timeout: {err}"),
            stdout_tail=_tail(out or ""),
            duration_secs=dur,
        )
    except FileNotFoundError:
        dur = time.perf_counter() - t0
        return ReplayOutcome(
            manifest_id=manifest_id,
            returncode=None,
            decision_mismatch=False,
            strict_timing_discrepancy=False,
            trace_divergence=False,
            stderr_tail=f"binary not found: {tarka_binary}",
            stdout_tail="",
            duration_secs=dur,
        )

    dur = time.perf_counter() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    decision_mismatch = DECISION_MISMATCH_MARKER in stdout
    strict_timing = STRICT_TIMING_DISCREPANCY in stdout
    trace_div = any(m in stdout for m in TRACE_DIVERGENCE_MARKERS)
    return ReplayOutcome(
        manifest_id=manifest_id,
        returncode=proc.returncode,
        decision_mismatch=decision_mismatch,
        strict_timing_discrepancy=strict_timing,
        trace_divergence=trace_div,
        stderr_tail=_tail(stderr),
        stdout_tail=_tail(stdout),
        duration_secs=dur,
    )


def _atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="engine_drift_", suffix=".json", dir=d or None, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _summary_to_dict(summary: RunSummary) -> dict[str, Any]:
    return {
        "engine_drift": summary.engine_drift,
        "checked_at": datetime.now(UTC).isoformat(),
        "sampled_manifest_ids": summary.sampled_manifest_ids,
        "errors": summary.errors,
        "outcomes": [
            {
                "manifest_id": o.manifest_id,
                "returncode": o.returncode,
                "decision_mismatch": o.decision_mismatch,
                "strict_timing_discrepancy": o.strict_timing_discrepancy,
                "trace_divergence": o.trace_divergence,
                "duration_secs": round(o.duration_secs, 3),
                "stderr_tail": o.stderr_tail,
                "stdout_tail": o.stdout_tail,
            }
            for o in summary.outcomes
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--tarka-binary",
        default=os.environ.get("TARKA_CLI_BINARY", "tarka"),
        help="Path to tarka CLI (default: $TARKA_CLI_BINARY or 'tarka' on PATH).",
    )
    p.add_argument("--sample-size", type=int, default=10)
    p.add_argument("--hours", type=int, default=24, help="Lookback window in hours.")
    p.add_argument(
        "--strict-sample-count",
        action="store_true",
        help="Exit 3 if fewer than --sample-size rows exist in the window.",
    )
    p.add_argument(
        "--fail-on-any-discrepancy",
        action="store_true",
        help=(
            "Also fail on strict-timing DISCREPANCY lines or trace step mismatch markers "
            "in replay stdout (default: decision mismatch only)."
        ),
    )
    p.add_argument(
        "--clear-lock-on-success",
        action="store_true",
        help="If ENGINE_DRIFT_LOCK_PATH exists and this run finds no drift, remove the lock file.",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--clickhouse-url",
        default=os.environ.get("CLICKHOUSE_HTTP_URL", "http://127.0.0.1:8123"),
    )
    p.add_argument(
        "--clickhouse-database",
        default=os.environ.get("CLICKHOUSE_DATABASE", "tarka_audit"),
    )
    p.add_argument(
        "--clickhouse-table",
        default=os.environ.get("CLICKHOUSE_TABLE", "evidence_manifests"),
    )
    p.add_argument(
        "--clickhouse-user", default=os.environ.get("CLICKHOUSE_USER", "default")
    )
    p.add_argument(
        "--clickhouse-password",
        default=os.environ.get("CLICKHOUSE_PASSWORD", ""),
    )
    p.add_argument(
        "--clickhouse-row-policy-tenant-id",
        default=os.environ.get("CLICKHOUSE_ROW_POLICY_TENANT_ID") or None,
    )
    p.add_argument("--clickhouse-connect-timeout", type=float, default=10.0)
    p.add_argument("--clickhouse-query-timeout", type=float, default=60.0)
    p.add_argument("--clickhouse-max-retries", type=int, default=3)
    p.add_argument("--replay-timeout-secs", type=float, default=120.0)
    p.add_argument(
        "--engine-drift-lock-path",
        default=os.environ.get("ENGINE_DRIFT_LOCK_PATH"),
        help="When set (or ENGINE_DRIFT_LOCK_PATH env), written on drift (JSON).",
    )
    p.add_argument(
        "--passthrough-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra argv tokens after 'tarka replay <uuid>' (e.g. --wasm-dir /path).",
    )
    p.add_argument(
        "--shuffle-manifest-order",
        action="store_true",
        help="Randomize replay order after fetch (extra entropy vs ClickHouse rand()).",
    )
    args = p.parse_args()
    _configure_logging(args.verbose)

    lock_path = args.engine_drift_lock_path

    try:
        _clickhouse_http_url(args.clickhouse_url)
    except ValueError as e:
        logger.error("%s", e)
        return 2

    try:
        manifest_ids = _fetch_random_manifest_ids(
            clickhouse_url=args.clickhouse_url,
            database=args.clickhouse_database,
            table=args.clickhouse_table,
            user=args.clickhouse_user,
            password=args.clickhouse_password,
            row_policy_tenant_id=args.clickhouse_row_policy_tenant_id,
            hours=args.hours,
            sample_size=args.sample_size,
            connect_timeout=args.clickhouse_connect_timeout,
            query_timeout=args.clickhouse_query_timeout,
            max_retries=args.clickhouse_max_retries,
        )
    except (ValueError, RuntimeError, httpx.HTTPError, OSError) as e:
        logger.error("ClickHouse sample query failed: %s", e)
        return 2

    if not manifest_ids:
        logger.error("No evidence_manifests rows in the last %s hours.", args.hours)
        return 2

    if args.strict_sample_count and len(manifest_ids) < args.sample_size:
        logger.error(
            "Strict sample count: got %s manifests, required %s",
            len(manifest_ids),
            args.sample_size,
        )
        return 3

    if len(manifest_ids) < args.sample_size:
        logger.warning(
            "Only %s manifest(s) in window (requested %s); continuing.",
            len(manifest_ids),
            args.sample_size,
        )

    order = list(manifest_ids)
    if args.shuffle_manifest_order:
        rng = random.SystemRandom()
        rng.shuffle(order)

    summary = RunSummary(sampled_manifest_ids=list(order))
    drift_manifests: list[str] = []

    for mid in order:
        logger.info("Replaying manifest_id=%s", mid)
        outcome = _run_tarka_replay(
            tarka_binary=args.tarka_binary,
            manifest_id=mid,
            replay_timeout_secs=args.replay_timeout_secs,
            extra_env={},
            passthrough_args=list(args.passthrough_arg),
        )
        summary.outcomes.append(outcome)

        if outcome.returncode is None:
            summary.errors.append(f"{mid}: replay did not complete ({outcome.stderr_tail})")
            logger.error("Replay failed for %s: %s", mid, outcome.stderr_tail)
            continue

        if outcome.returncode != 0:
            summary.errors.append(
                f"{mid}: tarka exit {outcome.returncode}: {outcome.stderr_tail}"
            )
            logger.error(
                "tarka replay non-zero exit=%s manifest=%s stderr=%s",
                outcome.returncode,
                mid,
                outcome.stderr_tail,
            )
            continue

        drift = outcome.decision_mismatch or (
            args.fail_on_any_discrepancy
            and (
                outcome.strict_timing_discrepancy or outcome.trace_divergence
            )
        )
        if drift:
            summary.engine_drift = True
            drift_manifests.append(mid)
            logger.error("Engine Drift detected manifest_id=%s", mid)

    print(json.dumps(_summary_to_dict(summary), indent=2))

    if summary.engine_drift:
        payload = {
            "block_rule_deployments": True,
            "reason": "engine_drift",
            "detected_at": datetime.now(UTC).isoformat(),
            "decision_mismatch_marker": DECISION_MISMATCH_MARKER,
            "drift_manifest_ids": drift_manifests,
            "fail_on_any_discrepancy": args.fail_on_any_discrepancy,
            "run": _summary_to_dict(summary),
        }
        if lock_path:
            try:
                _atomic_write_json(lock_path, payload)
                logger.error("Engine Drift lock written to %s", lock_path)
            except OSError as e:
                logger.error(
                    "Engine Drift detected but failed to write lock %s: %s",
                    lock_path,
                    e,
                )
        return 1

    if summary.errors:
        logger.error("Consistency check finished with %s replay error(s)", len(summary.errors))
        return 2

    if args.clear_lock_on_success and lock_path and os.path.isfile(lock_path):
        try:
            os.remove(lock_path)
            logger.info("Removed engine drift lock %s after clean run", lock_path)
        except OSError as e:
            logger.warning("Could not remove lock %s: %s", lock_path, e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
