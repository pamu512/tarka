"""
Saarthi hypothesis narrative generator (Prompt 195).

Turns DuckDB Scout ``HypothesisReport`` / coordinated-burst payloads into a fixed
two-sentence analyst summary via Gemini, with a deterministic fallback when
``GEMINI_API_KEY`` is unset or the model call fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

AttributionEngine = Literal["gemini", "fallback"]

_DEFAULT_MODEL = "gemini-1.5-pro"
_MAX_PAYLOAD_CHARS = 80_000

_SYSTEM_INSTRUCTION = (
    "You are Saarthi, a senior fraud analyst assistant. Given JSON from a DuckDB Scout "
    "coordinated-burst probe, write exactly two sentences for human analysts.\n"
    "Sentence 1: Describe the coordination threat (e.g. potential botnet, device farm, "
    "spoofed iPhone/Android fingerprint) using only evidence in the JSON.\n"
    "Sentence 2: State concrete scale and timing (distinct account count and elapsed hours "
    "between window_start_utc and window_end_utc).\n"
    "Rules: plain English only; no markdown; no bullet characters; exactly two sentences; "
    "each sentence must end with a period; do not invent counts or times not present in the JSON."
)

_USER_PREFIX = "DuckDB Scout burst evidence (JSON):\n"


def _gemini_model() -> str:
    return (os.environ.get("SAARTHI_GEMINI_MODEL") or _DEFAULT_MODEL).strip()


def _window_hours(start: datetime, end: datetime) -> float:
    delta = end - start
    return max(delta.total_seconds() / 3600.0, 1.0 / 60.0)


def _round_hours_label(hours: float) -> str:
    rounded = max(1, int(round(hours)))
    unit = "hour" if rounded == 1 else "hours"
    return f"{rounded} {unit}"


def extract_hypothesis_report(
    scout_result: dict[str, Any],
    *,
    hypothesis_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick the target burst row from a full scout payload or a single report."""
    if hypothesis_report is not None:
        if not isinstance(hypothesis_report, dict):
            raise TypeError("hypothesis_report must be an object")
        return hypothesis_report
    reports = scout_result.get("hypothesis_reports")
    if isinstance(reports, list) and reports:
        first = reports[0]
        if isinstance(first, dict):
            return first
    raise ValueError("scout_result contains no hypothesis_reports to narrate")


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def narrative_input_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Compact JSON-safe facts for Gemini / fallback."""
    ws = _parse_iso_datetime(report.get("window_start_utc"))
    we = _parse_iso_datetime(report.get("window_end_utc"))
    hours = _window_hours(ws, we) if ws is not None and we is not None else None
    return {
        "strategy": report.get("strategy") or "coordinated_burst",
        "fingerprint_kind": report.get("fingerprint_kind"),
        "fingerprint_value": report.get("fingerprint_value"),
        "distinct_account_count": report.get("distinct_account_count"),
        "window_start_utc": ws.isoformat() if ws else report.get("window_start_utc"),
        "window_end_utc": we.isoformat() if we else report.get("window_end_utc"),
        "window_hours_elapsed": round(hours, 2) if hours is not None else None,
        "confidence": report.get("confidence"),
        "account_ids_sample": (report.get("account_ids") or [])[:8],
        "scout_technical_narrative": report.get("narrative"),
    }


def normalize_two_sentence_narrative(text: str) -> str | None:
    """Return text if it is exactly two period-terminated sentences."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return None
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) != 2:
        return None
    normalized: list[str] = []
    for part in parts:
        if part[-1] not in ".!?":
            part = part + "."
        normalized.append(part)
    return " ".join(normalized)


def generate_hypothesis_narrative_fallback(report: dict[str, Any]) -> str:
    """
    Deterministic two-sentence summary (no LLM).

    Example: 50 accounts, canvas hash, 2-hour window → botnet + count/time sentences.
    """
    facts = narrative_input_from_report(report)
    kind = str(facts.get("fingerprint_kind") or "canvas_hash")
    fp = str(facts.get("fingerprint_value") or "unknown")
    count = int(facts.get("distinct_account_count") or 0)
    hours = facts.get("window_hours_elapsed")
    if hours is None:
        hours = 4.0
    hours_label = _round_hours_label(float(hours))

    fp_lower = fp.lower()
    if kind == "webgl_vendor":
        sentence_one = (
            f"A coordinated abuse cluster is reusing the same WebGL vendor string ({fp})."
        )
    elif "iphone" in fp_lower or "ios" in fp_lower:
        sentence_one = "A potential botnet is using a spoofed iPhone fingerprint."
    elif "android" in fp_lower:
        sentence_one = "A potential botnet is using a spoofed Android device fingerprint."
    else:
        sentence_one = "A potential botnet is using a shared spoofed device canvas fingerprint."

    account_word = "account" if count == 1 else "accounts"
    sentence_two = f"{count} {account_word} created in {hours_label}."
    return f"{sentence_one} {sentence_two}"


def _extract_gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        return ""
    first = parts[0]
    if isinstance(first, dict):
        return str(first.get("text") or "").strip()
    return ""


def generate_hypothesis_narrative_gemini(
    report: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> str | None:
    """Call Gemini; return normalized two-sentence text or ``None`` on failure."""
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    model_id = (model or _gemini_model()).strip()
    facts = narrative_input_from_report(report)
    try:
        payload_json = json.dumps(facts, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return None
    if len(payload_json) > _MAX_PAYLOAD_CHARS:
        payload_json = payload_json[:_MAX_PAYLOAD_CHARS]

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        f"?key={key}"
    )
    try:
        import httpx
    except ImportError:
        logger.warning("saarthi_hypothesis_narrative_httpx_missing")
        return None

    try:
        with httpx.Client(timeout=45.0) as client:
            res = client.post(
                url,
                json={
                    "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": _USER_PREFIX + payload_json}],
                        },
                    ],
                    "generationConfig": {
                        "temperature": 0.25,
                        "maxOutputTokens": 256,
                    },
                },
            )
        res.raise_for_status()
        data = res.json()
    except Exception:
        logger.exception("saarthi_hypothesis_narrative_gemini_failed")
        return None

    text = _extract_gemini_text(data if isinstance(data, dict) else {})
    return normalize_two_sentence_narrative(text)


def generate_hypothesis_narrative(
    scout_result: dict[str, Any],
    *,
    hypothesis_report: dict[str, Any] | None = None,
    api_key: str | None = None,
    model: str | None = None,
    prefer_gemini: bool = True,
) -> dict[str, Any]:
    """
    Build a two-sentence Saarthi narrative for one Scout burst.

    Returns ``{ narrative, attribution_engine, sentence_count }``.
    """
    report = extract_hypothesis_report(scout_result, hypothesis_report=hypothesis_report)
    engine: AttributionEngine = "fallback"
    narrative: str | None = None

    if prefer_gemini:
        narrative = generate_hypothesis_narrative_gemini(
            report,
            api_key=api_key,
            model=model,
        )
        if narrative:
            engine = "gemini"

    if not narrative:
        narrative = generate_hypothesis_narrative_fallback(report)
        engine = "fallback"

    return {
        "narrative": narrative,
        "attribution_engine": engine,
        "sentence_count": 2,
        "report_id": report.get("report_id"),
    }


def attach_narratives_to_scout_result(
    scout_result: dict[str, Any],
    *,
    prefer_gemini: bool = True,
) -> dict[str, Any]:
    """Mutate ``hypothesis_reports[*].saarthi_narrative`` in place; return ``scout_result``."""
    reports = scout_result.get("hypothesis_reports")
    if not isinstance(reports, list):
        return scout_result
    for report in reports:
        if not isinstance(report, dict):
            continue
        out = generate_hypothesis_narrative(
            scout_result,
            hypothesis_report=report,
            prefer_gemini=prefer_gemini,
        )
        report["saarthi_narrative"] = out["narrative"]
        report["saarthi_attribution_engine"] = out["attribution_engine"]
    return scout_result
