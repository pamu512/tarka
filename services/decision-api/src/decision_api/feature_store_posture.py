"""Online/offline feature-store ops posture — Redis velocity ≠ Feast/Flink product."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from decision_api.counter_manifest import (
    expected_feature_names,
    load_counter_manifest_v1,
    manifest_version,
)


def _parity_report_path(rules_path: str) -> Path:
    return Path(rules_path) / "counter_parity_last.json"


def _load_parity(rules_path: str) -> dict[str, Any] | None:
    path = _parity_report_path(rules_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def dual_diff_proven(parity: dict[str, Any] | None) -> bool:
    if not parity:
        return False
    mode = parity.get("mode")
    if parity.get("schema_id") == "tarka.counter_parity/v1":
        return mode == "dual_diff" and bool(parity.get("matched"))
    if mode == "dry_run":
        return False
    if mode in ("dual_diff", "redis_dual_diff"):
        return bool(parity.get("ok") or parity.get("matched"))
    return False


def redis_online_configured(*, redis_url: str = "") -> bool:
    url = (redis_url or "").strip() or os.environ.get("REDIS_URL", "").strip()
    if not url:
        url = os.environ.get("TARKA_REDIS_URL", "").strip()
    return bool(url)


def load_feature_store_ops_posture(
    *,
    rules_path: str,
    redis_url: str = "",
) -> dict[str, Any]:
    """Fail-closed Feast-class claim: dual-diff + Redis + manifest required; never Flink."""
    manifest = load_counter_manifest_v1()
    features = sorted(expected_feature_names())
    parity = _load_parity(rules_path)
    proven = dual_diff_proven(parity)
    redis_ok = redis_online_configured(redis_url=redis_url)
    ttl = float(os.environ.get("FEATURE_VELOCITY_TTL_SECONDS", "3600"))
    zero_fallback = os.environ.get("FEATURE_ZERO_FALLBACK", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    blockers: list[str] = []
    if not redis_ok:
        blockers.append("redis_online_unconfigured")
    if not proven:
        blockers.append("dual_diff_not_proven")
    if not features:
        blockers.append("manifest_empty")

    # ponytail: dual_diff+redis is L1 proof, not Feast online/offline product — claim stays false.
    feast_class_claim_allowed = False
    streaming_flink_claim_allowed = False

    return {
        "schema_id": "tarka.feature_store_ops_posture/v1",
        "online_store": {
            "backend": "redis_aggregates",
            "configured": redis_ok,
            "prefix": manifest.get("aggregate_prefix"),
            "ttl_seconds_default": ttl,
            "zero_fallback_on_miss": zero_fallback,
        },
        "online_serving": {
            "entity_query": "POST /v1/velocity/query (feature-service)",
            "parity_verify": "POST /v1/internal/parity/verify",
            "feature_names": features,
            "contract": "GET /v1/feature-serving-contract",
        },
        "offline_parity": {
            "dual_diff_proven": proven,
            "artifact_present": parity is not None,
            "mode": (parity or {}).get("mode"),
            "matched": (parity or {}).get("matched"),
            "generated_at": (parity or {}).get("ts")
            or (parity or {}).get("generated_at"),
            "path": str(_parity_report_path(rules_path)),
            "job": "scripts/oss/counter_parity_dual_diff.py",
            "replay": "scripts/replay/run_offline_parity.py",
            "verify": "POST /v1/internal/parity/verify",
            "same_feature_names_as_online": True,
        },
        "manifest": {
            "version": manifest_version(),
            "feature_count": len(features),
            "feature_names": features,
            "agg_key_version": os.environ.get("AGG_KEY_VERSION", "").strip() or None,
        },
        "streaming_plane": {
            "engine": "redis_velocity_windows",
            "not": ["flink", "feast", "kafka_feature_store"],
            "nats_analytics": "optional_sink_not_online_store",
        },
        "feast_class_claim_allowed": feast_class_claim_allowed,
        "streaming_flink_claim_allowed": streaming_flink_claim_allowed,
        "ops_ready": bool(redis_ok and proven and features),
        "blockers": blockers,
        "borrowed_from": "Feast-style online/offline feature contract (own Redis + dual_diff)",
        "vs_feast": (
            "Tarka Redis velocity + dual_diff parity ≠ Feast online store + offline "
            "materialization product. ops_ready means L1 parity evidence only."
        ),
        "honesty": (
            "Do not market Flink-class streaming or Feast-class feature store from "
            "Redis counters alone. dry_run / missing artifact never proves parity."
        ),
        "doc": "docs/docs/guides/feature-serving-contract.md",
        "ui": "/ops/counters",
    }
