"""Async warehouse backtest: keyset-stream OLAP → Rust ``tarka_rule_engine`` → Postgres aggregates."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

from analytics.engine import BaseAnalyticsEngine
from analytics.historical_stream import iter_backtest_row_chunks

from decision_api.config import settings
from decision_api.db import SessionLocal
from decision_api.deps import run_analytics_sync
from decision_api.json_rules import evaluate_adhoc_packs_json
from decision_api.models import BacktestRun, BacktestRunStatus
from decision_api.policy_routing import decision_from_rule_score

log = logging.getLogger("decision-api.backtest")

BACKTEST_CHUNK_SIZE = 10_000


def rule_pack_fingerprint_sha256(rule_pack: dict[str, Any]) -> str:
    raw = json.dumps(rule_pack, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _packs_for_evaluation(rule_pack: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(rule_pack, dict) and isinstance(rule_pack.get("rules"), list):
        return [rule_pack]
    return [{"version": 1, "name": "adhoc_backtest", "rules": []}]


def _row_to_features(row: dict[str, Any]) -> dict[str, Any]:
    feats: dict[str, Any] = {}
    raw = row.get("payload_json")
    if raw:
        try:
            if isinstance(raw, str):
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    feats.update(obj)
            elif isinstance(raw, dict):
                feats.update(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    eid = row.get("entity_id")
    if eid is not None:
        feats.setdefault("entity_id", str(eid))
    return feats


def _safe_next_chunk(iterator: Any) -> list[dict[str, Any]] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


async def run_backtest_job(job_id: uuid.UUID, engine: BaseAnalyticsEngine) -> None:
    """Execute a persisted job; enforces a **wall-clock** budget (default 60s) across all chunks + Rust work."""
    wall_s = max(1.0, float(getattr(settings, "backtest_job_timeout_seconds", 60.0)))
    deadline = time.monotonic() + wall_s
    ch_chunk_sec = max(
        5, min(45, int(settings.clickhouse_statement_timeout_ms) // 1000)
    )

    async with SessionLocal() as session:
        job = await session.get(BacktestRun, job_id)
        if job is None:
            log.warning("backtest job not found: %s", job_id)
            return
        if job.status != BacktestRunStatus.pending:
            return
        job.status = BacktestRunStatus.running
        await session.commit()
        fp_sha = job.rule_pack_fingerprint_sha256
        tenant_id = job.tenant_id
        tbl = job.analytics_table
        ws, we = job.window_start, job.window_end
        packs = _packs_for_evaluation(dict(job.rule_pack_json or {}))

    iterator = iter_backtest_row_chunks(
        engine,
        tbl,
        tenant_id,
        ws,
        we,
        chunk_size=BACKTEST_CHUNK_SIZE,
        clickhouse_max_execution_seconds=ch_chunk_sec,
    )

    rows_processed = 0
    rule_fired_rows = 0
    false_positives = 0
    false_negatives = 0
    historical_allows = 0
    decides_agree = 0

    try:
        while True:
            if time.monotonic() > deadline:
                async with SessionLocal() as session:
                    job = await session.get(BacktestRun, job_id)
                    if job:
                        job.status = BacktestRunStatus.failed_timeout
                        job.error_detail = "FAILED_TIMEOUT: exceeded wall clock budget for streaming backtest"
                        job.rows_processed = rows_processed
                        await session.commit()
                return

            chunk = await run_analytics_sync(lambda: _safe_next_chunk(iterator))
            if not chunk:
                break

            for row in chunk:
                feats = _row_to_features(row)
                eid = str(row.get("entity_id") or "").strip() or "unknown"
                tid = str(row.get("tenant_id") or tenant_id).strip() or tenant_id
                hits, _tags, delta, _c = evaluate_adhoc_packs_json(
                    packs,
                    feats,
                    [],
                    tid,
                    eid,
                    evaluation_mode="simulation",
                    record_telemetry=False,
                )
                act = str(row.get("decision") or "allow").strip().lower()
                if act not in ("allow", "review", "deny"):
                    act = "allow"
                pred = decision_from_rule_score(float(delta))
                rows_processed += 1
                if hits:
                    rule_fired_rows += 1
                if act == "allow":
                    historical_allows += 1
                    if pred != "allow":
                        false_positives += 1
                elif pred == "allow":
                    false_negatives += 1
                if pred == act:
                    decides_agree += 1

            async with SessionLocal() as session:
                job = await session.get(BacktestRun, job_id)
                if job:
                    job.rows_processed = rows_processed
                    await session.commit()

        metrics: dict[str, Any] = {
            "rows_processed": rows_processed,
            "rule_fired_rows": rule_fired_rows,
            "hit_rate": rule_fired_rows / max(1, rows_processed),
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "historical_allows": historical_allows,
            "false_positive_rate": false_positives / max(1, historical_allows),
            "decision_agreement_rate": decides_agree / max(1, rows_processed),
            "rule_pack_fingerprint_sha256": fp_sha,
            "analytics_table": tbl,
            "window_start": ws,
            "window_end": we,
            "chunk_size": BACKTEST_CHUNK_SIZE,
            "thresholds": {
                "deny_threshold": settings.deny_threshold,
                "review_threshold": settings.review_threshold,
            },
            "scoring_note": (
                "predicted_decision uses decision_from_rule_score(score_delta) from "
                "evaluate_adhoc_packs_json (Rust, simulation mode)."
            ),
        }
        async with SessionLocal() as session:
            job = await session.get(BacktestRun, job_id)
            if job:
                job.status = BacktestRunStatus.succeeded
                job.metrics_json = metrics
                job.error_detail = None
                job.rows_processed = rows_processed
                await session.commit()
    except Exception as e:
        log.exception("backtest job error: %s", job_id)
        async with SessionLocal() as session:
            job = await session.get(BacktestRun, job_id)
            if job:
                job.status = BacktestRunStatus.failed_error
                job.error_detail = f"FAILED_ERROR: {str(e)[:3900]}"
                job.rows_processed = rows_processed
                await session.commit()
