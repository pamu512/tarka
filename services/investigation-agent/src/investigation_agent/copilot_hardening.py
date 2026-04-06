"""
Structured copilot security helpers: audit sanitization, tool-claim grounding, tool allowlists.

Complements regex injection handling (see main._sanitize_message) and schema validation (tool_validation).
"""

from __future__ import annotations

import json
import re
from typing import Any

# UUID + common external ids (alphanumeric._-:@/)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

# Keys whose string values are treated as grounding tokens (successful tool results only)
_ID_RESULT_KEYS = frozenset(
    {
        "id",
        "case_id",
        "entity_id",
        "trace_id",
        "dispute_id",
        "batch_id",
        "center_entity_id",
        "from_id",
        "to_id",
    },
)

# Characters that can break instruction boundaries or carry HTML/script hints in audit text
_AUDIT_BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f<>{}]|javascript:|data:text|`{3,}")


def sanitize_audit_field(value: str, max_len: int) -> str:
    """Reduce client-supplied audit injection surface (prompt supply chain)."""
    s = (value or "")[:max_len]
    s = _AUDIT_BAD_CHARS.sub(" ", s)
    return " ".join(s.split())


def _tool_call_succeeded(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    return result.get("error") is None


def _collect_ids_from_nested(obj: Any, depth: int = 0, out: set[str] | None = None) -> set[str]:
    """Pull likely record ids from tool JSON (improves claim grounding vs UUID-only)."""
    if out is None:
        out = set()
    if depth > 6:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _ID_RESULT_KEYS and isinstance(v, str):
                s = v.strip()
                if len(s) >= 4:
                    out.add(s.lower())
            elif k in _ID_RESULT_KEYS and v is not None and not isinstance(v, (dict, list)):
                s = str(v).strip()
                if len(s) >= 4:
                    out.add(s.lower())
            else:
                _collect_ids_from_nested(v, depth + 1, out)
    elif isinstance(obj, list):
        for x in obj[:80]:
            _collect_ids_from_nested(x, depth + 1, out)
    return out


def build_source_reference_cards(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Structured \"what the copilot touched\" for UI transparency (weakness: opaque vendor copilots).
    One card per tool invocation; includes argument ids and ok/error.
    """
    cards: list[dict[str, Any]] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("tool") or "")
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        result = tc.get("result")
        ok = _tool_call_succeeded(result)
        card: dict[str, Any] = {
            "tool": name,
            "ok": ok,
        }
        if isinstance(args, dict):
            for key in ("case_id", "entity_id", "trace_id", "batch_id"):
                v = args.get(key)
                if v is not None and str(v).strip():
                    card[key] = str(v).strip()
        if isinstance(result, dict) and result.get("error"):
            card["error"] = str(result.get("error"))[:120]
        cards.append(card)
    return cards


def collect_grounding_tokens(tool_calls: list[dict[str, Any]]) -> frozenset[str]:
    """
    Tokens that may legitimately appear in tool-backed claims: UUIDs from successful tool I/O
    plus explicit ids from tool arguments (case_id, entity_id, trace_id, batch_id).
    """
    tokens: set[str] = set()
    blob_parts: list[str] = []

    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        args = tc.get("args")
        if isinstance(args, dict):
            for key in ("case_id", "entity_id", "trace_id", "batch_id"):
                v = args.get(key)
                if v is not None and str(v).strip():
                    s = str(v).strip()
                    tokens.add(s.lower())
                    blob_parts.append(s)
        result = tc.get("result")
        if not _tool_call_succeeded(result):
            continue
        try:
            blob_parts.append(json.dumps(result, default=str))
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict):
            for tid in _collect_ids_from_nested(result):
                tokens.add(tid)

    blob = "\n".join(blob_parts)
    for m in _UUID_RE.findall(blob):
        tokens.add(m.lower())

    return frozenset(tokens)


def enforce_tool_claim_grounding(
    claims: list[dict[str, str]],
    tool_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[str]]:
    """
    Downgrade source=tool claims that do not overlap grounding tokens from successful tools.
    Returns (adjusted_claims, human-readable adjustment reasons for logging / client).
    """
    adjustments: list[str] = []
    grounding = collect_grounding_tokens(tool_calls)
    if not grounding:
        out: list[dict[str, str]] = []
        for c in claims:
            if c.get("source") == "tool":
                out.append(
                    {
                        "text": c.get("text", ""),
                        "source": "unknown",
                    },
                )
                adjustments.append("no_successful_tool_payloads_for_grounding")
            else:
                out.append(dict(c))
        return out, adjustments

    out2: list[dict[str, str]] = []
    for c in claims:
        if c.get("source") != "tool":
            out2.append(dict(c))
            continue
        text = (c.get("text") or "").lower()
        ok = any(t in text for t in grounding if len(t) >= 4)
        if ok:
            out2.append(dict(c))
        else:
            out2.append(
                {
                    "text": c.get("text", ""),
                    "source": "unknown",
                },
            )
            adjustments.append("tool_claim_missing_grounding_token")

    return out2, adjustments


def parse_disabled_tools(raw: str) -> frozenset[str]:
    """Comma-separated tool names to omit from LLM tool list."""
    if not (raw or "").strip():
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def parse_sensitive_tools(raw: str) -> frozenset[str]:
    if not (raw or "").strip():
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def tool_error_acknowledgment_warnings(reply: str, tool_calls: list[dict[str, Any]]) -> list[str]:
    """
    If tools returned errors but prose does not mention failures, emit warnings for UI / QA.
    Heuristic: reply must contain 'error' or 'failed' or tool name near problem.
    """
    low = (reply or "").lower()
    warns: list[str] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        res = tc.get("result")
        if not isinstance(res, dict) or res.get("error") is None:
            continue
        name = str(tc.get("tool") or "")
        err = str(res.get("error", ""))[:80].lower()
        if "error" in low or "failed" in low or "not_found" in low or "forbidden" in low:
            if name and name.lower() in low:
                continue
            # still might be ok if generic error words present
            if "error" in low or "failed" in low:
                continue
        warns.append(f"tool_{name}_error_not_acknowledged:{err}")
    return warns


def deterministic_claim_support(
    claims: list[dict[str, str]],
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Per-claim overlap with successful tool JSON blobs (citation-grade hint, not legal proof).
    """
    blob_parts: list[str] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if not _tool_call_succeeded(tc.get("result")):
            continue
        try:
            blob_parts.append(json.dumps({"tool": tc.get("tool"), "result": tc.get("result")}, default=str))
        except (TypeError, ValueError):
            continue
    blob = "\n".join(blob_parts).lower()
    out: list[dict[str, Any]] = []
    for i, c in enumerate(claims):
        text = (c.get("text") or "").strip()
        src = c.get("source", "unknown")
        if not text:
            out.append({"claim_index": i, "supported": False, "method": "empty", "hint": None})
            continue
        tl = text.lower()
        # significant tokens: words length >= 4 or uuid-like fragments
        toks = re.findall(r"[a-z0-9][a-z0-9_-]{3,}", tl)
        hits = [t for t in toks if t in blob]
        supported = len(hits) >= 1 if src == "tool" else bool(hits)
        out.append(
            {
                "claim_index": i,
                "supported": supported,
                "method": "token_overlap",
                "hint": hits[:5] if hits else None,
            },
        )
    return out


# Scalar fields to surface as server-derived facts (not model-generated).
_DERIVED_TOP_KEYS = frozenset(
    {
        "id",
        "case_id",
        "dispute_id",
        "trace_id",
        "entity_id",
        "batch_id",
        "status",
        "priority",
        "recommended_action",
        "format",
        "filename",
    },
)
_DERIVED_NUMERIC_KEYS = frozenset({"row_count", "total", "count"})


def extract_derived_facts(
    tool_calls: list[dict[str, Any]],
    *,
    max_items: int = 48,
) -> list[dict[str, Any]]:
    """
    Deterministic facts extracted from successful tool JSON (for UI / policy; not model claims).
    """
    out: list[dict[str, Any]] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("tool") or "")
        res = tc.get("result")
        if not _tool_call_succeeded(res):
            continue
        if not isinstance(res, dict):
            continue
        for key in _DERIVED_TOP_KEYS:
            if key not in res or res[key] is None:
                continue
            val = res[key]
            if isinstance(val, (dict, list)):
                continue
            s = str(val).strip()
            if not s or len(s) > 240:
                continue
            out.append({"tool": name, "field": key, "value": val})
            if len(out) >= max_items:
                return out
        for key in _DERIVED_NUMERIC_KEYS:
            if key not in res:
                continue
            val = res[key]
            if isinstance(val, (int, float)) or (isinstance(val, str) and val.strip().isdigit()):
                out.append({"tool": name, "field": key, "value": val})
                if len(out) >= max_items:
                    return out
    return out


def strict_assurance_violations(
    *,
    claims: list[dict[str, str]],
    det_support: list[dict[str, Any]],
    ack_warns: list[str],
) -> list[str]:
    """
    In strict mode, any violation triggers a refusal to ship the model's investigative prose.
    """
    reasons: list[str] = []
    if ack_warns:
        reasons.append("tool_errors_not_acknowledged_in_prose")
    for row in det_support:
        if not isinstance(row, dict):
            continue
        i = row.get("claim_index")
        if not isinstance(i, int) or i < 0 or i >= len(claims):
            continue
        if claims[i].get("source") == "tool" and row.get("supported") is False:
            reasons.append(f"tool_claim_not_deterministically_supported:{i}")
    return reasons


def format_assurance_refusal(violations: list[str]) -> str:
    joined = "; ".join(violations) if violations else "policy"
    return (
        "This assistant summary was withheld under **strict assurance** settings. "
        f"Reasons: {joined}. "
        "Use **source_refs** and raw **tool_calls** below to review what succeeded or failed, "
        "then rephrase or retry after tools return clean data."
    )


async def llm_judge_claim_support(
    http_client: Any,
    *,
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int,
    claims: list[dict[str, str]],
    tool_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Optional second pass: LLM returns JSON { assessments: [{ claim_index, supported, reason }] }.
    Returns (parsed dict, error_message).
    """
    if not api_key:
        return None, "no_api_key"
    try:
        blob = json.dumps(tool_calls, default=str)[:14_000]
        payload_claims = json.dumps(claims[:30], default=str)
        user = (
            "You are a strict auditor. Given TOOL_CALLS_JSON (truncated) and CLAIMS, "
            "decide if each claim is directly supported by tool results (not speculation).\n"
            "Return ONLY compact JSON, no markdown:\n"
            '{"assessments":[{"claim_index":0,"supported":true,"reason":"short"}]}\n\n'
            f"TOOL_CALLS_JSON:\n{blob}\n\nCLAIMS:\n{payload_claims}"
        )
        url = f"{base_url.rstrip('/')}/chat/completions"
        r = await http_client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Output valid JSON only. Be conservative: unsupported if evidence is weak.",
                    },
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=45.0,
        )
        r.raise_for_status()
        data = r.json()
        content = str(data["choices"][0]["message"].get("content") or "").strip()
        # strip optional ```json fences
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return None, "judge_invalid_shape"
        return parsed, None
    except Exception as e:
        return None, str(e)[:200]


def filter_tool_definitions(
    definitions: list[dict[str, Any]],
    disabled: frozenset[str],
) -> list[dict[str, Any]]:
    if not disabled:
        return definitions
    out: list[dict[str, Any]] = []
    for d in definitions:
        fn = (d.get("function") or {}).get("name")
        if fn in disabled:
            continue
        out.append(d)
    return out
