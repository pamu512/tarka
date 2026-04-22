#!/usr/bin/env python3
from __future__ import annotations

"""Replay canonical decision logs against a target Decision API and classify drift."""


import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _build_replay_request(row: dict[str, Any]) -> dict[str, Any]:
    snap = row.get("payload_snapshot") or {}
    payload = snap.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    metadata = snap.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    out = {
        "tenant_id": row.get("tenant_id"),
        "event_type": row.get("event_type"),
        "entity_id": row.get("entity_id"),
        "payload": payload,
        "metadata": metadata,
    }
    return out


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _score_band(score: float) -> str:
    if score >= 80:
        return "deny_band"
    if score >= 50:
        return "review_band"
    return "allow_band"


def _inference_slice(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "confidence_tier": ctx.get("confidence_tier"),
        "top_signals": sorted(_as_str_list(ctx.get("top_signals"))),
        "graph_risk_score": float(ctx.get("graph_risk_score", 0.0) or 0.0),
        "external_signal_score": float(ctx.get("external_signal_score", 0.0) or 0.0),
        "policy_experiment_id": ctx.get("policy_experiment_id"),
        "ml_model": ctx.get("ml_model"),
    }


def _dependency_related_change(old_tags: set[str], new_tags: set[str], old_fallback: str, new_fallback: str) -> bool:
    dep_prefixes = ("graph:", "ml:", "opa:", "location:", "counter:", "external:", "enrichment:", "lists:")
    old_dep = {x for x in old_tags if x.startswith(dep_prefixes)}
    new_dep = {x for x in new_tags if x.startswith(dep_prefixes)}
    if old_dep != new_dep:
        return True
    if old_fallback != new_fallback:
        return True
    return False


def _classify_drift(row: dict[str, Any], fresh: dict[str, Any], score_delta_threshold: float) -> tuple[list[str], dict[str, Any]]:
    old_decision = str(row.get("decision"))
    new_decision = str(fresh.get("decision"))
    old_score = float(row.get("score", 0.0) or 0.0)
    new_score = float(fresh.get("score", 0.0) or 0.0)
    old_tags = set(_as_str_list(row.get("tags")))
    new_tags = set(_as_str_list(fresh.get("tags")))
    old_hits = set(_as_str_list(row.get("rule_hits")))
    new_hits = set(_as_str_list(fresh.get("rule_hits")))
    old_ctx = row.get("inference_context") if isinstance(row.get("inference_context"), dict) else {}
    new_ctx = fresh.get("inference_context") if isinstance(fresh.get("inference_context"), dict) else {}
    old_slice = _inference_slice(old_ctx)
    new_slice = _inference_slice(new_ctx)
    old_fallback = str(row.get("fallback_reason") or "")
    new_fallback = str(fresh.get("fallback_reason") or "")

    categories: set[str] = set()
    if old_hits != new_hits:
        categories.add("policy_drift")
    old_ml_model = str(old_slice.get("ml_model") or "")
    new_ml_model = str(new_slice.get("ml_model") or "")
    if old_ml_model != new_ml_model:
        categories.add("model_drift")
    if _dependency_related_change(old_tags, new_tags, old_fallback, new_fallback):
        categories.add("dependency_drift")

    score_delta = abs(new_score - old_score)
    decision_changed = old_decision != new_decision
    inference_changed = old_slice != new_slice
    if (decision_changed or inference_changed or score_delta >= score_delta_threshold) and not categories:
        categories.add("data_drift")

    detail = {
        "decision_changed": decision_changed,
        "score_delta": round(score_delta, 4),
        "score_band_changed": _score_band(old_score) != _score_band(new_score),
        "rule_hits_changed": old_hits != new_hits,
        "tags_changed": old_tags != new_tags,
        "inference_slice_changed": inference_changed,
        "old_fallback_reason": old_fallback,
        "new_fallback_reason": new_fallback,
        "old_inference_slice": old_slice,
        "new_inference_slice": new_slice,
    }
    return sorted(categories), detail


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay decision log JSONL into Decision API")
    parser.add_argument("--input", required=True, help="Path to decision-log.jsonl")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--allow-http-errors", action="store_true", help="Do not fail process when replay requests return non-200")
    parser.add_argument("--score-delta-threshold", type=float, default=5.0, help="Absolute score delta threshold for data drift classification")
    parser.add_argument("--sample-limit", type=int, default=20, help="Max drift samples included in output")
    parser.add_argument(
        "--max-allowed-decision-change-rate",
        type=float,
        default=-1.0,
        help="Fail if decision_change_rate exceeds this value (0-1). Negative disables budget gate.",
    )
    parser.add_argument(
        "--max-allowed-drift-rate",
        type=float,
        default=-1.0,
        help="Fail if any drift_rate exceeds this value (0-1). Negative disables budget gate.",
    )
    args = parser.parse_args()

    path = Path(args.input)
    if not path.is_file():
        raise SystemExit(f"missing input file: {path}")

    changed = 0
    score_band_changed = 0
    tags_changed = 0
    rule_hits_changed = 0
    inference_slice_changed = 0
    http_errors = 0
    drift_counts = {"policy_drift": 0, "model_drift": 0, "dependency_drift": 0, "data_drift": 0}
    drift_samples: list[dict[str, Any]] = []
    processed = 0
    with httpx.Client(timeout=8.0) as client:
        for row in _iter_jsonl(path):
            req = _build_replay_request(row)
            headers = {"content-type": "application/json"}
            if args.api_key:
                headers["x-api-key"] = args.api_key
            response = client.post(f"{args.base_url.rstrip('/')}/v1/decisions/evaluate", headers=headers, json=req)
            if response.status_code != 200:
                http_errors += 1
                continue
            fresh = response.json()
            cats, detail = _classify_drift(row, fresh, max(0.0, float(args.score_delta_threshold)))
            if detail["decision_changed"]:
                changed += 1
            if detail["score_band_changed"]:
                score_band_changed += 1
            if detail["tags_changed"]:
                tags_changed += 1
            if detail["rule_hits_changed"]:
                rule_hits_changed += 1
            if detail["inference_slice_changed"]:
                inference_slice_changed += 1
            for cat in cats:
                if cat in drift_counts:
                    drift_counts[cat] += 1
            if cats and len(drift_samples) < max(1, int(args.sample_limit)):
                drift_samples.append(
                    {
                        "trace_id": str(row.get("trace_id") or ""),
                        "categories": cats,
                        **detail,
                    }
                )
            processed += 1
            if processed >= max(1, args.limit):
                break

    scored = processed if processed else 1
    drift_rates = {k: round(v / scored, 4) if processed else 0.0 for k, v in drift_counts.items()}
    out = {
        "processed": processed,
        "http_errors": http_errors,
        "decision_changed": changed,
        "decision_change_rate": round((changed / scored), 4) if processed else 0.0,
        "score_band_changed": score_band_changed,
        "tags_changed": tags_changed,
        "rule_hits_changed": rule_hits_changed,
        "inference_slice_changed": inference_slice_changed,
        "drift_counts": drift_counts,
        "drift_rates": drift_rates,
        "samples": drift_samples,
        "input": str(path),
    }
    budget_failures: list[str] = []
    decision_budget = float(args.max_allowed_decision_change_rate)
    drift_budget = float(args.max_allowed_drift_rate)
    if decision_budget >= 0.0 and out["decision_change_rate"] > decision_budget:
        budget_failures.append(f"decision_change_rate={out['decision_change_rate']} > max_allowed_decision_change_rate={decision_budget}")
    if drift_budget >= 0.0:
        max_drift_rate = max(drift_rates.values()) if drift_rates else 0.0
        if max_drift_rate > drift_budget:
            budget_failures.append(f"max_drift_rate={max_drift_rate} > max_allowed_drift_rate={drift_budget}")
    out["budget_failures"] = budget_failures

    print(json.dumps(out, indent=2))
    if not args.allow_http_errors and http_errors > 0:
        return 1
    if budget_failures:
        return 2
    if processed > 0 and all(v == 0 for v in drift_counts.values()) and changed == 0:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
