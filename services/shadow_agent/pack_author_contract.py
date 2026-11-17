"""AI pack-author contract: schema + validator for LLM-authored rule packs.

The contract (PACK_AUTHOR.md) is loaded from this module's directory so code
always references the in-repo copy — never a stale wiki page.

Usage::

    from pack_author_contract import validate_ai_authored_pack

    result = validate_ai_authored_pack(doc)
    if not result["ok"]:
        print(result["errors"])
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from author_catalog import ai_allowed_fields, build_author_catalog
from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Contract text (loaded once; attached to LLM directive)
# ---------------------------------------------------------------------------

_CONTRACT_PATH = Path(__file__).resolve().parent / "PACK_AUTHOR.md"


def load_contract_text() -> str:
    """Return the full PACK_AUTHOR.md content. Raises if missing."""
    return _CONTRACT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Allowed values (mirrored from PACK_AUTHOR.md — single source of truth)
# ---------------------------------------------------------------------------

ALLOWED_FIELDS: frozenset[str] = ai_allowed_fields(
    build_author_catalog(
        graph_url=os.environ.get("GRAPH_SERVICE_URL") or "",
        growth_windows=None,
    )
)

ALLOWED_OPS: frozenset[str] = frozenset(
    {
        "eq",
        "not_eq",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        "exists",
        "not_exists",
        "is_true",
        "is_false",
    }
)

ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "login",
        "payment",
        "signup",
        "device",
        "session",
        "custom",
    }
)

SCORE_DELTA_MIN: float = 5.0
SCORE_DELTA_MAX: float = 30.0
MAX_RULES: int = 50
MAX_CONDITIONS: int = 20

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PackCondition(BaseModel):
    field: str = Field(..., min_length=1, max_length=128)
    op: str = Field(default="eq", min_length=1, max_length=32)
    value: Any = None


class PackRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    when: list[PackCondition] = Field(..., min_length=1, max_length=MAX_CONDITIONS)
    score_delta: float = Field(..., ge=SCORE_DELTA_MIN, le=SCORE_DELTA_MAX)
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIAuthoredPack(BaseModel):
    """Pydantic model enforcing the AI pack-author contract."""

    name: str = Field(..., min_length=1, max_length=120)
    version: Literal[1] = 1
    mode: Literal["shadow"] = "shadow"
    is_ai_authored: Literal[True]
    authored_by: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    evidence: dict[str, Any] = Field(default_factory=dict)
    rules: list[PackRule] = Field(..., min_length=1, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _validate_contract_constraints(self) -> "AIAuthoredPack":
        # authored_by must not contain Tarka brand names
        lower = self.authored_by.lower()
        for brand in ("tarka", "saarthi"):
            if brand in lower:
                raise ValueError(f"authored_by must not contain Tarka brand name '{brand}'")
        return self


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_ai_authored_pack(
    doc: dict[str, Any],
    allowed_fields: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Validate an AI-authored pack against the contract.

    Returns ``{"ok": True, "pack": <parsed>}`` on success, or
    ``{"ok": False, "errors": [...]}`` on failure.  Invalid packs are
    dropped — never canaried.

    ``allowed_fields`` overrides import-time ``ALLOWED_FIELDS`` (seed ∪ identity
    ∪ aliases). Decision-api write path passes the live tenant set.
    """
    errors: list[str] = []
    fields = allowed_fields or ALLOWED_FIELDS

    # --- structural parse via pydantic ---
    try:
        pack = AIAuthoredPack.model_validate(doc)
    except Exception as exc:
        return {"ok": False, "errors": [f"schema: {exc}"]}

    # --- field / op allow-list enforcement ---
    for rule in pack.rules:
        for cond in rule.when:
            if cond.field not in fields:
                errors.append(f"rule {rule.id}: unknown field '{cond.field}'")
            if cond.op not in ALLOWED_OPS:
                errors.append(f"rule {rule.id}: disallowed op '{cond.op}'")
            # event_type value check
            if cond.field == "event_type" and cond.op == "eq":
                if isinstance(cond.value, str) and cond.value not in ALLOWED_EVENT_TYPES:
                    errors.append(f"rule {rule.id}: unknown event_type value '{cond.value}'")
            if cond.field == "event_type" and cond.op == "in":
                if isinstance(cond.value, list):
                    for v in cond.value:
                        if isinstance(v, str) and v not in ALLOWED_EVENT_TYPES:
                            errors.append(f"rule {rule.id}: unknown event_type value '{v}'")

    if errors:
        return {"ok": False, "errors": errors}

    return {"ok": True, "pack": pack.model_dump(mode="json")}


MIN_SOP_TEXT_CHARS = 24
_SOP_QUOTE_MIN = 12
_FORBIDDEN_DECISIONS = frozenset({"allow", "deny", "promote"})


def evidence_is_thin(report: dict[str, Any] | None) -> bool:
    """True when the hypothesis has no report id, fingerprint, and account count."""
    if not isinstance(report, dict):
        return True
    report_id = str(report.get("report_id") or "").strip()
    fingerprint = str(report.get("fingerprint_value") or "").strip()
    try:
        count = int(report.get("distinct_account_count"))
    except (TypeError, ValueError):
        count = 0
    return not report_id or not fingerprint or count < 2


def classify_sop_chunks(chunks: list[Any] | None) -> dict[str, Any]:
    """Split caller chunks into allowlisted text vs blocked.

    ``chunks is None`` means SOP was not supplied (state ``absent``).
    An empty list, thin text, or ``allowlisted is not True`` is ``missing``.
    """
    if chunks is None:
        return {"state": "absent", "allowlisted": [], "blocked": []}
    if not isinstance(chunks, list):
        return {"state": "missing", "allowlisted": [], "blocked": []}
    allowlisted: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    for item in chunks:
        if not isinstance(item, dict):
            blocked.append({"id": "", "text": "", "reason": "not_object"})
            continue
        cid = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if item.get("allowlisted") is not True or not cid or len(text) < MIN_SOP_TEXT_CHARS:
            reason = "unallowlisted" if item.get("allowlisted") is not True else "thin_or_empty"
            blocked.append({"id": cid, "text": text, "reason": reason})
            continue
        allowlisted.append({"id": cid, "text": text})
    if not allowlisted:
        return {"state": "missing", "allowlisted": [], "blocked": blocked}
    return {"state": "ready", "allowlisted": allowlisted, "blocked": blocked}


def sop_draft_errors(doc: dict[str, Any], chunks: list[Any] | None) -> list[str]:
    """Reject live decisions, unallowlisted SOP text, and SOP used as a feature."""
    if not isinstance(doc, dict):
        return ["draft_not_object"]
    errors: list[str] = []
    if doc.get("mode") != "shadow":
        errors.append("mode must be shadow")
    for key in ("decision", "action", "promote"):
        if key in doc:
            errors.append(f"forbidden field {key}")
    classified = classify_sop_chunks(chunks)
    allow_ids = {row["id"] for row in classified["allowlisted"]}
    allow_text = [row["text"] for row in classified["allowlisted"]]
    blocked = classified["blocked"]
    try:
        raw = json.dumps(doc, ensure_ascii=False)
    except (TypeError, ValueError):
        return ["draft_not_serializable"]
    for item in blocked:
        text = item.get("text") or ""
        if len(text) >= _SOP_QUOTE_MIN and text in raw:
            errors.append("unallowlisted sop text")
            break
    evidence = doc.get("evidence") if isinstance(doc.get("evidence"), dict) else {}
    for key in ("sop_chunk_ids", "okf_chunk_ids"):
        ids = evidence.get(key)
        if ids is None:
            continue
        if not isinstance(ids, list) or not {str(i) for i in ids} <= allow_ids:
            errors.append("sop id not allowlisted")
    rules = doc.get("rules") if isinstance(doc.get("rules"), list) else []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = rule.get("id")
        for key in ("decision", "action"):
            val = str(rule.get(key) or "").strip().lower()
            if val in _FORBIDDEN_DECISIONS:
                errors.append(f"rule {rid}: forbidden {key}")
        if isinstance(rule.get("score_delta"), str):
            errors.append("sop text is not a score")
        for cond in rule.get("when") or []:
            if not isinstance(cond, dict):
                continue
            field = str(cond.get("field") or "")
            value = cond.get("value")
            for text in [*allow_text, *(item.get("text") or "" for item in blocked)]:
                if not text:
                    continue
                if field == text or value == text or (isinstance(value, str) and text in value):
                    errors.append("sop text is not a feature")
                    break
    return errors


def validate_suggested_shadow_rule_template(rule: dict[str, Any]) -> dict[str, Any]:
    """Validate a single ``suggested_shadow_rule`` dict from scout.

    Wraps it in a minimal pack envelope and runs the full contract validator.
    Useful for ensuring scout's own ``suggested_shadow_rule()`` output is legal
    even without an LLM in the loop.
    """
    pack_envelope: dict[str, Any] = {
        "name": f"scout_{rule.get('id', 'unknown')}",
        "version": 1,
        "mode": "shadow",
        "is_ai_authored": True,
        "authored_by": "scout",
        "rules": [rule],
    }
    return validate_ai_authored_pack(pack_envelope)


# ---------------------------------------------------------------------------
# JSON Schema export (for sending to LLMs alongside the directive)
# ---------------------------------------------------------------------------


def ai_authored_pack_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for AIAuthoredPack (useful in LLM prompts)."""
    return AIAuthoredPack.model_json_schema()


def build_llm_directive() -> str:
    """Build the full directive string to send to an LLM backend.

    Combines the markdown contract with the JSON Schema.
    """
    contract = load_contract_text()
    schema = json.dumps(
        ai_authored_pack_json_schema(),
        indent=2,
        ensure_ascii=False,
    )
    return (
        f"{contract}\n\n"
        f"---\n\n"
        f"## JSON Schema (machine-readable)\n\n"
        f"Your output MUST validate against this schema:\n\n"
        f"```json\n{schema}\n```\n"
    )
