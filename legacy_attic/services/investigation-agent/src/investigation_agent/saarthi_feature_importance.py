"""Saarthi feature-importance ranking for case triage (Prompt 166)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

import httpx

AttributionEngine = Literal["mock", "gemini", "heuristic"]


def _clamp01(n: float) -> float:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def rank_feature_importance_heuristic(body: dict[str, Any]) -> dict[str, Any]:
    """Mirror of ``frontend/src/lib/saarthi/featureImportance.ts`` heuristic."""
    ctx = body.get("inference_context") if isinstance(body.get("inference_context"), dict) else {}
    risk_score = float(body.get("risk_score") or 0)
    decision = str(body.get("decision") or "review")
    trace_id = str(body.get("trace_id") or "")
    rule_hits = body.get("rule_hits") if isinstance(body.get("rule_hits"), list) else []
    tags = body.get("tags") if isinstance(body.get("tags"), list) else []

    raw: list[dict[str, Any]] = []
    seen: set[str] = set()

    def push(row: dict[str, Any]) -> None:
        sid = str(row["signal_id"])
        if sid in seen:
            return
        seen.add(sid)
        raw.append(row)

    for d in ctx.get("driver_explain") or []:
        if not isinstance(d, dict):
            continue
        push(
            {
                "signal_id": f"driver:{d.get('reason', '')}",
                "label": str(d.get("label") or d.get("reason") or "Driver"),
                "category": str(d.get("category") or "driver"),
                "weight": 0.55
                + _clamp01(ctx.get("graph_risk_score", 0)) * 0.1
                + (0.12 if d.get("category") == "velocity" else 0.05),
            },
        )

    for f in ctx.get("ml_top_factors") or []:
        if not isinstance(f, dict):
            continue
        impact = str(f.get("impact") or "").lower()
        push(
            {
                "signal_id": f"ml:{f.get('code', '')}",
                "label": str(f.get("description") or f.get("code") or "ML factor"),
                "category": "ml",
                "weight": 0.35 + (0.2 if "high" in impact else 0.08),
            },
        )

    for s in ctx.get("top_signals") or []:
        push(
            {
                "signal_id": f"signal:{s}",
                "label": str(s).replace("_", " "),
                "category": "signal",
                "weight": 0.28,
            },
        )

    v24 = int(ctx.get("velocity_events_24h") or 0)
    push(
        {
            "signal_id": "metric:velocity_24h",
            "label": f"Velocity burst ({v24} events / 24h)",
            "category": "velocity",
            "weight": 0.2 + min(0.45, v24 / 80),
        },
    )
    gr = _clamp01(ctx.get("graph_risk_score", 0))
    push(
        {
            "signal_id": "metric:graph_risk",
            "label": f"Graph linkage risk ({gr * 100:.0f}%)",
            "category": "graph",
            "weight": 0.18 + gr * 0.42,
        },
    )
    nt = _clamp01(ctx.get("network_trust", 1))
    push(
        {
            "signal_id": "metric:network_trust",
            "label": f"Network trust ({nt * 100:.0f}%)",
            "category": "integrity",
            "weight": 0.12 + (1 - nt) * 0.35,
        },
    )

    for hit in rule_hits:
        hid = str(hit).strip()
        if not hid:
            continue
        push(
            {
                "signal_id": f"rule:{hid}",
                "label": f"Rule fired: {hid}",
                "category": "policy",
                "weight": 0.42,
            },
        )

    if not raw:
        push(
            {
                "signal_id": "score:baseline",
                "label": f"Baseline model score ({risk_score:.1f}/100)",
                "category": "model",
                "weight": 1.0,
            },
        )

    raw.sort(key=lambda r: float(r["weight"]), reverse=True)
    top = raw[:8]
    sum_w = sum(float(r["weight"]) for r in top) or 1.0
    items = [
        {
            "signal_id": r["signal_id"],
            "label": r["label"],
            "category": r.get("category"),
            "importance": round(float(r["weight"]) / sum_w * 1000) / 10,
        }
        for r in top
    ]

    lead_label = items[0]["label"] if items else "composite risk"
    lead_rationale = (
        f"Saarthi ranks {lead_label} as the strongest explanatory driver for this {decision} "
        f"at {risk_score:.1f}/100 — chart shows relative weight across velocity, graph, integrity, and policy signals."
        if items
        else f"Insufficient structured drivers on the audit to rank feature importance for trace {trace_id}."
    )

    return {
        "items": items,
        "lead_rationale": lead_rationale,
        "attribution_engine": "heuristic",
        "_tags": tags,
    }


def _parse_gemini_json(text: str) -> dict[str, Any] | None:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if fence:
        t = fence.group(1).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


async def rank_feature_importance_saarthi(body: dict[str, Any]) -> dict[str, Any]:
    """Try Gemini JSON ranking; fall back to heuristic."""
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    model = (os.environ.get("SAARTHI_GEMINI_MODEL") or "gemini-1.5-pro").strip()
    if not api_key:
        out = rank_feature_importance_heuristic(body)
        out["attribution_engine"] = "mock"
        return out

    try:
        payload_json = json.dumps(body, separators=(",", ":"))[:80_000]
    except (TypeError, ValueError):
        return rank_feature_importance_heuristic(body)

    system = (
        "You are Saarthi, a fraud analyst assistant. Given a decision audit JSON, return ONLY valid JSON "
        'with keys: items (array of {signal_id, label, importance 0-100, category}), lead_rationale (string). '
        "Rank 4-8 signals that best explain the risk_score. importance values should sum to approximately 100. "
        "Prefer velocity, graph, integrity/geo, rules, and ML drivers present in inference_context."
    )
    user = f"Rank feature importance for this audit:\n{payload_json}"

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(
                url,
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
                },
            )
        res.raise_for_status()
        data = res.json()
        candidates = data.get("candidates") or []
        parts = (
            (candidates[0] or {}).get("content", {}).get("parts", [])
            if candidates
            else []
        )
        text = ""
        if parts and isinstance(parts[0], dict):
            text = str(parts[0].get("text") or "")
        parsed = _parse_gemini_json(text)
        if parsed and isinstance(parsed.get("items"), list) and parsed.get("lead_rationale"):
            items_out = []
            for row in parsed["items"][:10]:
                if not isinstance(row, dict):
                    continue
                items_out.append(
                    {
                        "signal_id": str(row.get("signal_id") or "signal"),
                        "label": str(row.get("label") or row.get("signal_id") or "Signal"),
                        "importance": float(row.get("importance") or 0),
                        "category": row.get("category"),
                    },
                )
            if items_out:
                return {
                    "items": items_out,
                    "lead_rationale": str(parsed["lead_rationale"]),
                    "attribution_engine": "gemini",
                }
    except Exception:
        pass

    return rank_feature_importance_heuristic(body)
