"""System benchmarking — compare live path latency vs sub-millisecond target (Prompt 178)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

SUB_MILLISECOND_TARGET_MS = 1.0
DEFAULT_SAMPLE_ROUNDS = 7
NEAR_TARGET_MULTIPLIER = 2.0

BenchStatus = Literal["on_target", "near_target", "over_target", "unavailable"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _percentile(sorted_samples: list[float], pct: float) -> float | None:
    if not sorted_samples:
        return None
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    rank = (len(sorted_samples) - 1) * (pct / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_samples) - 1)
    frac = rank - lo
    return sorted_samples[lo] * (1.0 - frac) + sorted_samples[hi] * frac


def _summarize_samples(samples: list[float]) -> dict[str, float | None]:
    if not samples:
        return {"min_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None, "mean_ms": None}
    ordered = sorted(samples)
    mean = sum(ordered) / len(ordered)
    return {
        "min_ms": round(ordered[0], 4),
        "p50_ms": round(_percentile(ordered, 50) or ordered[0], 4),
        "p95_ms": round(_percentile(ordered, 95) or ordered[-1], 4),
        "max_ms": round(ordered[-1], 4),
        "mean_ms": round(mean, 4),
    }


def classify_vs_target(
    p95_ms: float | None, *, target_ms: float = SUB_MILLISECOND_TARGET_MS
) -> BenchStatus:
    if p95_ms is None:
        return "unavailable"
    if p95_ms <= target_ms:
        return "on_target"
    if p95_ms <= target_ms * NEAR_TARGET_MULTIPLIER:
        return "near_target"
    return "over_target"


def _bench_row(
    *,
    probe_id: str,
    label: str,
    plane: str,
    samples: list[float],
    target_ms: float = SUB_MILLISECOND_TARGET_MS,
    critical: bool = True,
    detail: str | None = None,
) -> dict[str, Any]:
    stats = _summarize_samples(samples)
    p95 = stats["p95_ms"]
    status = classify_vs_target(p95 if isinstance(p95, (int, float)) else None, target_ms=target_ms)
    delta = None
    if p95 is not None:
        delta = round(float(p95) - target_ms, 4)
    return {
        "id": probe_id,
        "label": label,
        "plane": plane,
        "critical": critical,
        "target_ms": target_ms,
        "samples_ms": [round(s, 4) for s in samples],
        "sample_count": len(samples),
        **stats,
        "delta_p95_vs_target_ms": delta,
        "meets_sub_ms_target": status == "on_target",
        "status": status,
        "detail": detail,
    }


async def _probe_redis_once(redis_client: Any | None, redis_url: str) -> dict[str, Any]:
    if redis_client is None and not (redis_url or "").strip():
        return {"reachable": False, "latency_ms": None}
    t0 = time.perf_counter()
    try:
        if redis_client is not None:
            await redis_client.ping()
        else:
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url.strip(), decode_responses=True)
            try:
                await client.ping()
            finally:
                await client.aclose()
        ms = (time.perf_counter() - t0) * 1000.0
        return {"reachable": True, "latency_ms": round(ms, 4)}
    except Exception as exc:
        logger.debug("system_benchmarking redis ping failed: %s", exc)
        return {"reachable": False, "latency_ms": None}


async def _sample_redis_ping(redis_client: Any | None, redis_url: str, rounds: int) -> list[float]:
    out: list[float] = []
    for _ in range(rounds):
        row = await _probe_redis_once(redis_client, redis_url)
        if row.get("reachable") and row.get("latency_ms") is not None:
            out.append(float(row["latency_ms"]))
        else:
            break
    return out


async def _sample_redis_kv(redis_client: Any | None, redis_url: str, rounds: int) -> list[float]:
    key = "tarka:bench:kv"
    payload = "x"
    samples: list[float] = []
    try:
        if redis_client is not None:
            client = redis_client
            close = False
        else:
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url.strip(), decode_responses=True)
            close = True
        try:
            for i in range(rounds):
                t0 = time.perf_counter()
                await client.set(f"{key}:{i % 3}", payload, ex=30)
                await client.get(f"{key}:{i % 3}")
                samples.append((time.perf_counter() - t0) * 1000.0)
        finally:
            if close:
                await client.aclose()
    except Exception as exc:
        logger.debug("system_benchmarking redis kv failed: %s", exc)
        return []
    return samples


def _sample_in_process_floor(rounds: int) -> list[float]:
    samples: list[float] = []
    payload = {"entity_id": "bench", "amount": 42, "flags": [1, 2, 3]}
    raw = json.dumps(payload)
    for _ in range(rounds):
        t0 = time.perf_counter()
        obj = json.loads(raw)
        _ = hash(json.dumps(obj, sort_keys=True))
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


async def _sample_http_get(
    http: httpx.AsyncClient, url: str, rounds: int
) -> tuple[list[float], str | None]:
    if not url.strip():
        return [], "endpoint not configured"
    samples: list[float] = []
    try:
        for _ in range(rounds):
            t0 = time.perf_counter()
            resp = await http.get(url.strip(), timeout=3.0)
            if resp.status_code >= 400:
                return [], f"HTTP {resp.status_code}"
            samples.append((time.perf_counter() - t0) * 1000.0)
    except Exception as exc:
        logger.warning("benchmark http probe failed url=%s", url.strip(), exc_info=exc)
        return [], "probe failed"
    return samples, None


async def build_system_benchmarking_payload(
    *,
    http: httpx.AsyncClient,
    redis_client: Any | None,
    redis_url: str,
    sample_rounds: int = DEFAULT_SAMPLE_ROUNDS,
) -> dict[str, Any]:
    rounds = max(3, min(int(sample_rounds), 25))
    probes: list[dict[str, Any]] = []

    floor = _sample_in_process_floor(rounds)
    probes.append(
        _bench_row(
            probe_id="in_process_floor",
            label="In-process JSON + hash floor",
            plane="host",
            samples=floor,
            critical=False,
            detail="Local CPU baseline — not a production SLO path.",
        ),
    )

    redis_ping = await _sample_redis_ping(redis_client, redis_url, rounds)
    probes.append(
        _bench_row(
            probe_id="redis_ping",
            label="Redis PING RTT",
            plane="data_plane",
            samples=redis_ping,
            detail="Edge → Redis single round-trip.",
        ),
    )

    redis_kv = await _sample_redis_kv(redis_client, redis_url, rounds)
    probes.append(
        _bench_row(
            probe_id="redis_kv_roundtrip",
            label="Redis GET/SET micro-bench",
            plane="data_plane",
            samples=redis_kv,
            detail="One SET + GET pair per sample.",
        ),
    )

    rule_url = (os.environ.get("RULE_ENGINE_BENCH_URL") or "http://127.0.0.1:8778/health").strip()
    rule_samples, rule_err = await _sample_http_get(http, rule_url, rounds)
    probes.append(
        _bench_row(
            probe_id="rule_engine_health",
            label="Rule engine health RTT",
            plane="decision_plane",
            samples=rule_samples,
            detail=rule_err or rule_url,
        ),
    )

    decision_url = (
        os.environ.get("DECISION_API_BENCH_URL") or "http://127.0.0.1:8001/v1/health"
    ).strip()
    dec_samples, dec_err = await _sample_http_get(http, decision_url, rounds)
    probes.append(
        _bench_row(
            probe_id="decision_api_health",
            label="Decision API health RTT",
            plane="decision_plane",
            samples=dec_samples,
            detail=dec_err or decision_url,
        ),
    )

    ingress_url = (os.environ.get("INGRESS_BENCH_URL") or "http://127.0.0.1:8003/v1/health").strip()
    ing_samples, ing_err = await _sample_http_get(http, ingress_url, rounds)
    probes.append(
        _bench_row(
            probe_id="integration_ingress_health",
            label="Integration ingress health RTT",
            plane="ingress_plane",
            samples=ing_samples,
            detail=ing_err or ingress_url,
        ),
    )

    critical = [p for p in probes if p.get("critical") and p.get("p95_ms") is not None]
    on_target = [p for p in critical if p.get("status") == "on_target"]
    over = [p for p in critical if p.get("status") == "over_target"]
    worst = max(critical, key=lambda p: float(p.get("p95_ms") or 0), default=None)

    return {
        "updated_at": _now_iso(),
        "source": "live",
        "target": {
            "name": "Sub-millisecond",
            "description": "Hot-path p95 latency budget for edge data + decision planes.",
            "p95_target_ms": SUB_MILLISECOND_TARGET_MS,
            "near_target_multiplier": NEAR_TARGET_MULTIPLIER,
        },
        "methodology": {
            "sample_rounds": rounds,
            "primary_metric": "p95_ms",
            "comparison": "p95_ms <= target_ms → on target",
        },
        "probes": probes,
        "summary": {
            "critical_probe_count": len([p for p in probes if p.get("critical")]),
            "on_target_count": len(on_target),
            "over_target_count": len(over),
            "all_critical_on_target": len(critical) > 0 and len(on_target) == len(critical),
            "worst_probe_id": worst.get("id") if worst else None,
            "worst_p95_ms": worst.get("p95_ms") if worst else None,
        },
    }
