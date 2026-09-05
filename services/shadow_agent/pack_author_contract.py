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


def validate_ai_authored_pack(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate an AI-authored pack against the contract.

    Returns ``{"ok": True, "pack": <parsed>}`` on success, or
    ``{"ok": False, "errors": [...]}`` on failure.  Invalid packs are
    dropped — never canaried.
    """
    errors: list[str] = []

    # --- structural parse via pydantic ---
    try:
        pack = AIAuthoredPack.model_validate(doc)
    except Exception as exc:
        return {"ok": False, "errors": [f"schema: {exc}"]}

    # --- field / op allow-list enforcement ---
    for rule in pack.rules:
        for cond in rule.when:
            if cond.field not in ALLOWED_FIELDS:
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
