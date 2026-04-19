"""Investigation agent with proper LLM tool-use loop."""

import json
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from investigation_agent import batch_store, copilot_analytics, feedback_store, knowledge_store, review_store
from investigation_agent.answer_structure import parse_structured_sections, structured_sections_prompt_block
from investigation_agent.config import (
    effective_embedding_api_key,
    effective_embedding_base_url,
    settings,
)
from investigation_agent.copilot_hardening import (
    build_source_reference_cards,
    deterministic_claim_support,
    enforce_tool_claim_grounding,
    extract_derived_facts,
    filter_tool_definitions,
    format_assurance_refusal,
    llm_judge_claim_support,
    parse_sensitive_tools,
    sanitize_audit_field,
    strict_assurance_violations,
    tool_error_acknowledgment_warnings,
)
from investigation_agent.evidence_bundle import build_evidence_bundle_draft
from investigation_agent.governance import (
    governance_profile_label,
    governance_profile_references,
    normalize_governance_profile,
    regional_system_prompt_append,
)
from investigation_agent.integration_contract import (
    INTEGRATION_CONTRACT_VERSION,
    build_integration_snapshot,
    effective_disabled_tools,
)
from investigation_agent.personas import (
    DEFAULT_COPILOT_PERSONA,
    CopilotPersona,
    build_copilot_system_prompt,
    list_personas,
)
from investigation_agent.playbooks import (
    list_playbooks,
    playbook_system_append,
    playbooks_catalog_fingerprint,
    validate_playbook_id,
)
from investigation_agent.production_config import (
    production_config_errors,
    raise_if_production_invalid,
    runtime_readiness_errors,
)
from investigation_agent.rate_limit import MinuteRateLimiter
from investigation_agent.reports.case_summary_pdf import render_case_summary_pdf
from investigation_agent.tool_validation import validate_tool_arguments
from investigation_agent.tools import TOOL_DEFINITIONS, TOOL_DISPATCH, is_analyst_allowed
from investigation_agent.workflows.registry import (
    format_workflow_system_append,
    list_workflows,
    normalize_workflow_params,
    validate_workflow_id,
    workflows_catalog_fingerprint,
)

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from observability import get_metrics, setup_observability  # noqa: E402

_TARKA_CLAIMS_MARKER = "\nTARKA_CLAIMS_JSON="
_MAX_PARSED_CLAIMS = 40
_MAX_CLAIM_TEXT_LEN = 2000

# ---------- auth ----------

_valid_api_keys: frozenset[str] | None = None


def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = os.environ.get("API_KEYS", "").strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys


async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if settings.copilot_require_investigation_api_key:
        if not keys:
            raise HTTPException(
                status_code=503,
                detail="COPILOT_REQUIRE_INVESTIGATION_API_KEY is set but API_KEYS is empty",
            )
    elif not keys:
        return
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


@asynccontextmanager
async def lifespan(application: FastAPI):
    raise_if_production_invalid(settings)
    if not settings.copilot_production_mode and not _get_api_keys():
        log.warning(
            "investigation-agent: API_KEYS unset — /v1/chat is network-reachable without service auth "
            "(set API_KEYS and optionally COPILOT_REQUIRE_INVESTIGATION_API_KEY=true for production).",
        )
    if not settings.copilot_production_mode and (settings.allowed_analysts or "*").strip() == "*":
        log.warning(
            "investigation-agent: ALLOWED_ANALYSTS=* — every caller who reaches the service may use copilot tools.",
        )
    if settings.copilot_production_mode and settings.copilot_include_platform_audit_in_prompt:
        log.warning(
            "investigation-agent: COPILOT_INCLUDE_PLATFORM_AUDIT_IN_PROMPT=true in production — "
            "client-supplied platform_audit is an injection/supply-chain surface; prefer false unless required.",
        )
    application.state.rate_limiter = MinuteRateLimiter(settings.copilot_rate_limit_per_minute) if settings.copilot_rate_limit_per_minute > 0 else None
    application.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
    )
    yield
    await application.state.http.aclose()


app = FastAPI(
    title="Tarka Investigation Agent",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "investigation-agent")


class ChatMessage(BaseModel):
    role: str
    content: str


class CopilotContextOptions(BaseModel):
    """Client preferences for platform-audit attachment; server enforces track_historical_actions."""

    model_config = ConfigDict(extra="forbid")

    track_historical_actions: bool = True
    only_session: bool = False
    skip_session_actions: bool = False
    session_started_at: str | None = Field(default=None, max_length=48)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    batch_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional UUID from POST /v1/batch/ingest for tabular analysis tools.",
    )
    playbook_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional built-in investigation playbook (GET /v1/playbooks).",
    )
    persona: CopilotPersona = Field(
        default=DEFAULT_COPILOT_PERSONA,
        description="Copilot persona: investigation (evidence-first) or orchestrator (workflow efficiency, less rework). See GET /v1/personas.",
    )
    messages: list[ChatMessage] = Field(default_factory=list)
    platform_audit: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional recent platform audit events for analyst-context suggestions.",
    )
    context_options: CopilotContextOptions | None = None
    workflow_id: str | None = Field(
        default=None,
        max_length=80,
        description="Optional SOP workflow manifest id (GET /v1/workflows); appends system instructions.",
    )
    workflow_params: dict[str, Any] | None = Field(
        default=None,
        description="Key/value template params for the workflow (e.g. audience, report_label).",
    )


class EvidenceSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=80)
    reply: str = Field(default="", max_length=80_000)
    claims: list[dict[str, str]] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    claims_deterministic_support: list[dict[str, Any]] = Field(default_factory=list)
    answer_sections: dict[str, Any] = Field(default_factory=dict)
    turn_id: str | None = Field(default=None, max_length=80)
    prompt_version: str | None = Field(default=None, max_length=32)
    workflow_id: str | None = Field(default=None, max_length=80)
    persona: str = Field(default="investigation", max_length=32)


class EvidenceSummaryChatRequest(ChatRequest):
    """ChatRequest body plus optional deterministic id for stable replay tests."""

    turn_id: str | None = Field(default=None, max_length=80)


class CaseSummaryReportBody(BaseModel):
    """Client sends the same fields returned by POST /v1/chat to render a PDF (no server-side chat replay)."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    title: str = Field(default="Case summary", max_length=256)
    turn_id: str | None = Field(default=None, max_length=80)
    case_id: str | None = Field(default=None, max_length=128)
    workflow_id: str | None = Field(default=None, max_length=80)
    prompt_version: str | None = Field(default=None, max_length=32)
    reply: str = Field(..., max_length=80_000)
    answer_sections: dict[str, Any] = Field(default_factory=dict)
    claims: list[dict[str, str]] | None = None


class TurnBundleReportBody(BaseModel):
    """Export a turn as Markdown + structured JSON for review tools (no server-side replay)."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    title: str = Field(default="Investigation turn", max_length=256)
    turn_id: str | None = Field(default=None, max_length=80)
    case_id: str | None = Field(default=None, max_length=128)
    workflow_id: str | None = Field(default=None, max_length=80)
    prompt_version: str | None = Field(default=None, max_length=32)
    reply: str = Field(..., max_length=80_000)
    answer_sections: dict[str, Any] = Field(default_factory=dict)
    claims: list[dict[str, str]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    source_refs: list[dict[str, Any]] | None = None


REFERENCE_MODE_SYSTEM_APPEND = (
    "REFERENCE MODE: Live case, graph, and decision APIs may be absent or unused for this turn. "
    "Ground analysis in workflows, SOPs, and uploaded reference memos (knowledge/RAG) unless tool outputs state otherwise. "
    "Do not assert live production case facts without tool or memo support."
)


def _summary_confidence_label(claims: list[dict[str, str]], support_rows: list[dict[str, Any]]) -> tuple[str, float]:
    if not claims:
        return "medium", 0.5
    total = max(len(claims), 1)
    supported = 0
    for row in support_rows:
        if isinstance(row, dict) and row.get("supported") is True:
            supported += 1
    ratio = supported / total
    if ratio >= 0.75:
        return "high", round(ratio, 3)
    if ratio >= 0.4:
        return "medium", round(ratio, 3)
    return "low", round(ratio, 3)


def _build_turn_bundle_payload(rb: TurnBundleReportBody) -> dict[str, Any]:
    title = (rb.title or "Investigation turn").strip() or "Investigation turn"
    md_lines = [f"# {title}", ""]
    if rb.turn_id:
        md_lines.extend([f"**turn_id:** {rb.turn_id}", ""])
    if rb.case_id:
        md_lines.extend([f"**case_id:** {rb.case_id}", ""])
    if rb.workflow_id:
        md_lines.extend([f"**workflow_id:** {rb.workflow_id}", ""])
    md_lines.extend(["## Analyst reply", "", (rb.reply or "").strip(), ""])
    ans = rb.answer_sections if isinstance(rb.answer_sections, dict) else {}
    if ans:
        md_lines.extend(["## Structured sections", ""])
        for k, v in ans.items():
            md_lines.extend([f"### {k}", "", str(v), ""])
    claims = rb.claims or []
    if claims:
        md_lines.extend(["## Claims", ""])
        for c in claims:
            if isinstance(c, dict):
                md_lines.append(f"- ({c.get('source', '?')}) {c.get('text', '')}")
        md_lines.append("")
    tc = rb.tool_calls or []
    if tc:
        md_lines.extend(["## Tool calls (summary)", "", f"_(count: {len(tc)})_", ""])
    return {
        "format": "turn_bundle_v1",
        "markdown": "\n".join(md_lines).strip(),
        "structured": {
            "tenant_id": rb.tenant_id,
            "analyst_id": rb.analyst_id,
            "turn_id": rb.turn_id,
            "case_id": rb.case_id,
            "workflow_id": rb.workflow_id,
            "prompt_version": rb.prompt_version,
            "reply": rb.reply,
            "answer_sections": ans,
            "claims": claims,
            "tool_calls": rb.tool_calls,
            "source_refs": rb.source_refs,
        },
    }


class KnowledgeIngestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    title: str = Field(default="untitled", max_length=256)
    body: str = Field(..., max_length=130_000)


class TurnReviewBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    turn_id: str = Field(..., max_length=80)
    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    status: Literal["approved", "rejected"] = Field(...)
    note: str | None = Field(default=None, max_length=2000)


class ChatFeedbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    turn_id: str = Field(..., max_length=80)
    rating: int = Field(..., ge=-1, le=1, description="-1 down, 0 neutral, 1 up")
    note: str | None = Field(default=None, max_length=2000)
    claim_indices: list[int] | None = None
    tenant_id: str | None = Field(default=None, max_length=128)
    analyst_id: str | None = Field(default=None, max_length=128)
    tags: dict[str, Any] | None = None


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def _execute_tool(
    http: httpx.AsyncClient,
    name: str,
    arguments: dict[str, Any],
    tenant_id: str,
    analyst_id: str,
) -> dict[str, Any]:
    fn = TOOL_DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    norm, verr = validate_tool_arguments(name, arguments)
    if verr:
        return {"error": "invalid_tool_arguments", "detail": verr}
    assert norm is not None
    if name == "get_batch_profile":
        return await fn(http, tenant_id, analyst_id, norm["batch_id"])
    if name == "query_batch_rows":
        return await fn(
            http,
            tenant_id,
            analyst_id,
            norm["batch_id"],
            norm["offset"],
            norm["limit"],
            norm["columns"],
        )
    if name == "aggregate_batch_column":
        return await fn(
            http,
            tenant_id,
            analyst_id,
            norm["batch_id"],
            norm["column"],
            norm["mode"],
        )
    if name == "get_case":
        return await fn(http, norm["case_id"], tenant_id, analyst_id)
    if name == "list_cases":
        return await fn(http, tenant_id, analyst_id, norm["limit"])
    if name == "subgraph":
        return await fn(http, norm["entity_id"], tenant_id, analyst_id, norm["depth"])
    if name == "get_entity_tags":
        return await fn(http, norm["entity_id"], tenant_id, analyst_id)
    if name == "get_entity_velocity":
        return await fn(http, norm["entity_id"], tenant_id, analyst_id)
    if name == "get_decision_audit":
        return await fn(http, norm["trace_id"], tenant_id, analyst_id)
    if name == "subgraph_with_velocity":
        return await fn(
            http,
            norm["entity_id"],
            tenant_id,
            analyst_id,
            norm["depth"],
            norm["max_velocity_nodes"],
        )
    if name == "export_outcome_labeled_dataset":
        return await fn(
            http,
            tenant_id,
            analyst_id,
            norm["case_limit"],
            norm["dispute_limit"],
            norm["resolved_disputes_only"],
        )
    if name == "ingest_labeled_rows":
        return await fn(
            http,
            tenant_id,
            analyst_id,
            norm["rows"],
            norm["clear_existing"],
        )
    if name == "get_stored_labeled_dataset":
        return await fn(http, tenant_id, analyst_id)
    if name == "run_replay_ab_comparison":
        return await fn(
            http,
            tenant_id,
            analyst_id,
            norm["rules_variant_a"],
            norm["rules_variant_b"],
            norm["limit"],
            norm["trace_ids"],
        )
    if name == "search_knowledge":
        return await fn(http, tenant_id, analyst_id, norm["query"], norm["limit"])
    if name == "compare_entity_queue_snapshot":
        return await fn(http, norm["entity_id"], tenant_id, analyst_id, norm["list_limit"])
    return {"error": "dispatch_failure"}


def _effective_chat_model() -> str:
    m = (settings.copilot_chat_model or "").strip()
    return m if m else settings.openai_model


def _merge_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    if not usages:
        return {}
    pt = sum(int(u.get("prompt_tokens") or 0) for u in usages)
    ct = sum(int(u.get("completion_tokens") or 0) for u in usages)
    tt = sum(int(u.get("total_tokens") or 0) for u in usages)
    if tt == 0 and (pt or ct):
        tt = pt + ct
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}


async def _llm_plain_completion(
    http: httpx.AsyncClient,
    system: str,
    messages: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Single chat/completions call without tools (reference deployments, empty tool surface)."""
    if not settings.openai_api_key:
        return "[offline mode] Configure OPENAI_API_KEY for LLM.", {}
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    llm_url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    conversation = [{"role": "system", "content": system}] + messages
    body: dict[str, Any] = {
        "model": _effective_chat_model(),
        "messages": conversation,
        "max_tokens": settings.copilot_max_completion_tokens,
    }
    r = await http.post(llm_url, headers=headers, json=body, timeout=120.0)
    r.raise_for_status()
    data = r.json()
    choice = data["choices"][0]
    msg = choice["message"]
    usage = data.get("usage")
    return str(msg.get("content", "")), usage if isinstance(usage, dict) else {}


async def _maybe_prefetch_rag_to_system(
    http: httpx.AsyncClient,
    system: str,
    messages: list[dict[str, Any]],
    tenant_id: str,
    analyst_id: str,
) -> str:
    if not settings.copilot_plain_prefetch_rag:
        return system
    if not effective_embedding_api_key() or not settings.copilot_knowledge_embeddings:
        return system
    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last = str(m.get("content", "") or "")
            break
    last = last.strip()
    if not last:
        return system
    try:
        data = await knowledge_store.search_async(
            http,
            use_embeddings=bool(effective_embedding_api_key()),
            api_key=effective_embedding_api_key(),
            base_url=effective_embedding_base_url(),
            embed_model=settings.copilot_embedding_model,
            tenant_id=tenant_id,
            analyst_id=analyst_id,
            query=last[:8000],
            limit=5,
            keyword_weight=settings.copilot_rag_keyword_weight,
        )
    except Exception:
        log.warning("prefetch_rag_failed", exc_info=True)
        return system
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list) or not hits:
        return system
    lines = [
        "",
        "REFERENCE KNOWLEDGE (prefetched from investigation memos; verify critical facts):",
    ]
    for i, h in enumerate(hits[:5], 1):
        if not isinstance(h, dict):
            continue
        title = str(h.get("title") or "untitled")[:200]
        snip = str(h.get("snippet") or "")[:900]
        lines.append(f"{i}. [{title}] {snip}")
    return system + "\n" + "\n".join(lines)


async def _llm_tool_loop(
    http: httpx.AsyncClient,
    system: str,
    messages: list[dict[str, Any]],
    tenant_id: str,
    analyst_id: str,
    tool_defs: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Run the tool-use loop: send to LLM, execute any tool calls, repeat."""
    all_tool_calls: list[dict[str, Any]] = []
    usages: list[dict[str, Any]] = []

    if not settings.openai_api_key:
        return "[offline mode] Configure OPENAI_API_KEY for LLM tool-use.", all_tool_calls, {}, 0

    if not tool_defs:
        raw, u = await _llm_plain_completion(http, system, messages)
        usages.append(u)
        return raw, all_tool_calls, _merge_usage(usages), len(usages)

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    llm_url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    conversation = [{"role": "system", "content": system}] + messages

    max_rounds = settings.copilot_max_tool_iterations
    max_tok = settings.copilot_max_completion_tokens

    for _ in range(max_rounds):
        body: dict[str, Any] = {
            "model": _effective_chat_model(),
            "messages": conversation,
            "tools": tool_defs,
            "tool_choice": "auto",
            "max_tokens": max_tok,
        }
        r = await http.post(llm_url, headers=headers, json=body, timeout=60.0)
        r.raise_for_status()
        data = r.json()
        u = data.get("usage")
        if isinstance(u, dict):
            usages.append(u)
        choice = data["choices"][0]
        msg = choice["message"]

        if msg.get("tool_calls"):
            conversation.append(msg)
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}
                result = await _execute_tool(http, fn_name, fn_args, tenant_id, analyst_id)
                all_tool_calls.append({"tool": fn_name, "args": fn_args, "result": result})
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, default=str)[:8000],
                    }
                )
        else:
            return str(msg.get("content", "")), all_tool_calls, _merge_usage(usages), len(usages)

    return "Reached maximum tool iterations. Please refine your question.", all_tool_calls, _merge_usage(usages), len(usages)


_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"(system|assistant)\s*:\s*", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"pretend\s+(to\s+be|you\s+are)", re.IGNORECASE),
    re.compile(r"(jailbreak|DAN|bypass|override|hack)\s", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),
    re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>", re.IGNORECASE),
    re.compile(r"```(python|bash|sh|powershell|javascript|sql)", re.IGNORECASE),
]


def _sanitize_message(content: str, max_chars: int | None = None) -> str:
    """Strip potential prompt injection patterns from user messages."""
    cap = settings.copilot_max_message_chars if max_chars is None else max_chars
    sanitized = content[:cap]
    for pattern in _INJECTION_PATTERNS:
        sanitized = pattern.sub("[blocked]", sanitized)
    return sanitized.strip()


def _detect_injection(content: str) -> bool:
    """Return True if message looks like a prompt injection attempt."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            return True
    return False


_OUTPUT_BLOCKLIST = [
    "OPENAI_API_KEY",
    "API_KEYS=",
    "secret_key",
    "password",
    "-----BEGIN",
    "Authorization: Bearer",
    "sk-",
]

_SCOPE_ID_RE = re.compile(r"^[a-zA-Z0-9._@:-]+$")
_MAX_AUDIT_EVENTS = 40
_SESSION_NOISE_RES = re.compile(
    r"investigation:copilot|copilot:chat|admin:session|auth:session|admin:sessions",
    re.IGNORECASE,
)
_SESSION_NOISE_DETAIL = re.compile(
    r"session token|refresh session|sso session|idle session",
    re.IGNORECASE,
)


def _validate_scope_id(label: str, value: str) -> None:
    v = (value or "").strip()
    if not v or len(v) > 128 or not _SCOPE_ID_RE.match(v):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")


def _confidence_label_from_support_rate(rate: float) -> str:
    if rate >= 0.8:
        return "high"
    if rate >= 0.5:
        return "medium"
    return "low"


def _normalize_platform_audit_row(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    flags_in = raw.get("flags")
    safe_flags: list[dict[str, str]] = []
    if isinstance(flags_in, list):
        for f in flags_in[:12]:
            if isinstance(f, dict):
                safe_flags.append(
                    {
                        "type": sanitize_audit_field(str(f.get("type", "")), 64),
                        "severity": sanitize_audit_field(str(f.get("severity", "")), 16),
                        "note": sanitize_audit_field(str(f.get("note", "")), 200),
                    }
                )
    return {
        "id": str(raw.get("id", ""))[:64],
        "ts": str(raw.get("ts", ""))[:40],
        "user_id": str(raw.get("user_id", ""))[:64],
        "user_name": sanitize_audit_field(str(raw.get("user_name", "")), 128),
        "action": sanitize_audit_field(str(raw.get("action", "")), 32),
        "resource": sanitize_audit_field(str(raw.get("resource", "")), 256),
        "detail": sanitize_audit_field(str(raw.get("detail", "")), 256),
        "ip": str(raw.get("ip", ""))[:45],
        "flags": safe_flags,
    }


def _normalize_platform_audit_rows(raw: list[Any] | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:_MAX_AUDIT_EVENTS]:
        row = _normalize_platform_audit_row(item)
        if row:
            out.append(row)
    return out


def _filter_session_noise_audit(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        r = str(e.get("resource", ""))
        if _SESSION_NOISE_RES.search(r):
            continue
        d = str(e.get("detail", ""))
        if _SESSION_NOISE_DETAIL.search(d):
            continue
        out.append(e)
    return out


def _format_platform_audit_for_prompt(events: list[dict[str, Any]] | None, max_items: int = 25) -> str:
    if not events:
        return ""
    lines: list[str] = []
    for e in events[:max_items]:
        ts = str(e.get("ts", ""))[:22]
        who = str(e.get("user_name") or e.get("user_id") or "?")
        action = str(e.get("action", ""))
        resource = str(e.get("resource", ""))
        detail = str(e.get("detail") or "")[:140]
        flags = e.get("flags") or []
        flag_parts: list[str] = []
        if isinstance(flags, list):
            for f in flags:
                if isinstance(f, dict):
                    flag_parts.append(f"{f.get('type', '?')}({f.get('severity', '?')})")
        flag_s = ", ".join(flag_parts) if flag_parts else ""
        line = f"- {ts} | {who} | {action} {resource} | {detail}"
        if flag_s:
            line += f" | FLAGS: {flag_s}"
        lines.append(line)
    return (
        "RECENT PLATFORM AUDIT (recent user actions across the product; not a substitute for case tools):\n"
        + "\n".join(lines)
        + "\n\nUse this when the analyst asks about team behavior, risk patterns, or what to do next after "
        "suspicious activity. Tie suggestions to specific audit lines when relevant. For case facts, still use tools. "
        "Flagged rows often warrant governance review, session checks, or rule peer review — say so explicitly."
    )


def _validate_output(reply: str) -> str:
    """Redact any secrets or sensitive data that leaked into the response."""
    for pattern in _OUTPUT_BLOCKLIST:
        if pattern.lower() in reply.lower():
            reply = re.sub(re.escape(pattern) + r"[^\s]*", "[REDACTED]", reply, flags=re.IGNORECASE)
    if len(reply) > 5000:
        reply = reply[:5000] + "\n\n[Response truncated for safety]"
    return reply


def _parse_tarka_claims_reply(raw_reply: str) -> tuple[str, list[dict[str, str]], str | None]:
    """
    Split prose from mandatory claims trailer. Returns (prose, claims, warning_or_none).
    Each claim: {"text": str, "source": "tool" | "unknown"}.
    """
    fallback = "Assistant did not emit a valid TARKA_CLAIMS_JSON trailer; treat the narrative as unverified (source=unknown)."
    if _TARKA_CLAIMS_MARKER not in raw_reply:
        return raw_reply.strip(), [{"text": fallback, "source": "unknown"}], "claims_trailer_missing"

    prose, _, rest = raw_reply.rpartition(_TARKA_CLAIMS_MARKER)
    prose = prose.strip()
    rest = rest.strip()
    if not rest:
        return prose or raw_reply.strip(), [{"text": "Empty TARKA_CLAIMS_JSON payload.", "source": "unknown"}], "claims_empty_json"

    try:
        data = json.loads(rest)
    except json.JSONDecodeError:
        return raw_reply.strip(), [{"text": "Invalid JSON after TARKA_CLAIMS_JSON.", "source": "unknown"}], "claims_json_invalid"

    claims_in = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims_in, list):
        return prose or raw_reply.strip(), [{"text": "claims must be a JSON array.", "source": "unknown"}], "claims_not_array"

    out: list[dict[str, str]] = []
    for c in claims_in[:_MAX_PARSED_CLAIMS]:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text", "")).strip()[:_MAX_CLAIM_TEXT_LEN]
        src = str(c.get("source", "")).strip().lower()
        if src not in ("tool", "unknown"):
            src = "unknown"
        if text:
            out.append({"text": text, "source": src})

    if not out:
        return prose, [{"text": "No valid claims after parsing trailer.", "source": "unknown"}], "claims_empty_list"

    return prose, out, None


@app.middleware("http")
async def _request_guards_and_security_headers(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cl = request.headers.get("content-length")
        if cl:
            try:
                n = int(cl)
            except ValueError:
                n = 0
            else:
                if n > settings.copilot_max_request_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "request body too large"},
                    )
    lim = getattr(request.app.state, "rate_limiter", None)
    if lim and request.method == "POST" and request.url.path.startswith("/v1/"):
        key = (
            request.headers.get("x-api-key")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        if not lim.allow(key):
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded; retry after a minute"},
                headers={"Retry-After": "60"},
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/v1/ready")
async def ready():
    """
    Readiness probe: data directory writable (SQLite/RAG). Does not call the LLM.
    Use with GET /v1/health for liveness vs readiness in orchestrators.
    """
    errs = runtime_readiness_errors()
    if errs:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "errors": errs},
        )
    return {"status": "ready"}


@app.get("/v1/health")
async def health():
    gov = normalize_governance_profile(settings.ai_governance_profile)
    eff = effective_disabled_tools(settings)
    prod_cfg = production_config_errors(settings)
    return {
        "status": "ok",
        "ai_governance_profile": gov,
        "ai_governance_label": governance_profile_label(gov),
        "copilot_prompt_version": settings.copilot_prompt_version,
        "production": {
            "mode": settings.copilot_production_mode,
            "config_ok": not bool(prod_cfg),
            "config_errors": prod_cfg,
            "rate_limit_per_minute": settings.copilot_rate_limit_per_minute or None,
            "max_request_body_bytes": settings.copilot_max_request_body_bytes,
        },
        "integration": build_integration_snapshot(settings, disabled_tools=eff),
        "copilot_features": {
            "structured_sections": settings.copilot_structured_sections,
            "judge_pass": settings.copilot_enable_judge_pass,
            "knowledge_ingest": True,
            "knowledge_embeddings": bool(
                settings.copilot_knowledge_embeddings and effective_embedding_api_key(),
            ),
            "reference_mode": settings.copilot_reference_mode,
            "plain_chat": settings.copilot_plain_chat,
            "plain_prefetch_rag": settings.copilot_plain_prefetch_rag,
            "embedding_base_url_override": bool((settings.copilot_embedding_base_url or "").strip()),
            "feedback_persistence": True,
            "maker_checker": bool((settings.copilot_reviewer_secret or "").strip()),
            "assurance_mode": settings.copilot_assurance_mode,
            "derived_facts": bool(
                settings.copilot_derived_facts or settings.copilot_assurance_mode == "strict",
            ),
            "turn_review_persistence": True,
            "hide_tools_without_upstream": settings.copilot_hide_tools_without_upstream,
            "evidence_bundle_format": settings.copilot_evidence_bundle_format,
            "evidence_bundle_v1": settings.copilot_evidence_bundle_format in ("v1", "dual"),
            "analytics_enabled": settings.copilot_analytics_enabled,
            "analytics_sink": settings.copilot_analytics_sink if settings.copilot_analytics_enabled else None,
            "playbooks_fingerprint": playbooks_catalog_fingerprint(),
            "copilot_personas": [p["id"] for p in list_personas()],
            "workflows_fingerprint": workflows_catalog_fingerprint(),
            "copilot_workflows": [w["id"] for w in list_workflows()],
        },
    }


@app.get("/v1/integration")
async def integration_surface():
    """
    Machine-readable integration contract: tool surface, upstream flags, profile id.
    For adapter parity tests and Saarthi Pro / third-party stack mapping (no raw URLs).
    """
    return build_integration_snapshot(settings, disabled_tools=effective_disabled_tools(settings))


@app.get("/v1/setup")
async def setup_diagnostics():
    """
    First-run checklist for minimal-integration deployments: LLM keys, embedding/RAG, optional upstreams.
    Does not call external networks (config-derived only).
    """
    eff = effective_embedding_api_key()
    emb_url = effective_embedding_base_url()
    chat_url = (settings.openai_base_url or "").strip()
    checklist: list[dict[str, Any]] = [
        {
            "id": "llm_api_key",
            "ok": bool(settings.openai_api_key),
            "detail": "Set OPENAI_API_KEY (or compatible) for chat completions.",
        },
        {
            "id": "embedding_key_for_rag",
            "ok": bool(not settings.copilot_knowledge_embeddings) or bool(eff),
            "detail": "Hybrid RAG needs an embedding-capable key (OPENAI_API_KEY or COPILOT_EMBEDDING_API_KEY).",
        },
        {
            "id": "upstream_integrations",
            "ok": bool(
                (settings.case_api_url or "").strip() or (settings.decision_api_url or "").strip() or (settings.graph_service_url or "").strip(),
            ),
            "detail": "Optional: CASE_API_URL, DECISION_API_URL, GRAPH_SERVICE_URL for live investigation tools.",
        },
    ]
    return {
        "schema": "saarthi_setup_v1",
        "reference_mode": settings.copilot_reference_mode,
        "plain_chat": settings.copilot_plain_chat,
        "plain_prefetch_rag": settings.copilot_plain_prefetch_rag,
        "llm": {
            "chat_base_url": settings.openai_base_url,
            "chat_model": _effective_chat_model(),
            "api_key_configured": bool(settings.openai_api_key),
        },
        "embeddings": {
            "base_url": emb_url,
            "model": settings.copilot_embedding_model,
            "api_key_configured": bool(eff),
            "separate_from_chat_url": emb_url.rstrip("/") != chat_url.rstrip("/"),
        },
        "knowledge": {
            "hybrid_rag_configured": bool(settings.copilot_knowledge_embeddings and eff),
        },
        "checklist": checklist,
        "integration": build_integration_snapshot(settings, disabled_tools=effective_disabled_tools(settings)),
    }


@app.get("/v1/personas")
async def personas_list():
    """Copilot personas (investigation vs workflow orchestrator); same tools and safety, different system-prompt emphasis."""
    return {"personas": list_personas()}


@app.get("/v1/playbooks")
async def playbooks_list():
    """Built-in typology playbooks (system-prompt workflow hints; tools still explicit)."""
    return {"playbooks": list_playbooks()}


@app.get("/v1/workflows")
async def workflows_list():
    """SOP-style workflow manifests (GET ids + POST /v1/chat workflow_id + workflow_params)."""
    return {"workflows": list_workflows()}


@app.post("/v1/evidence/summary")
async def evidence_summary(body: EvidenceSummaryRequest, request: Request):
    """
    Deterministic case/graph risk summary with citation cards and confidence labels.

    Uses the same internal chat/tooling path as /v1/chat, then returns a compact
    analyst-facing shape keyed to issue #11 acceptance criteria.
    """
    _validate_scope_id("tenant_id", body.tenant_id)
    _validate_scope_id("analyst_id", body.analyst_id)
    if body.case_id:
        _validate_scope_id("case_id", body.case_id)
    if not is_analyst_allowed(body.analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")

    claims = [c for c in body.claims if isinstance(c, dict)]
    refs = [r for r in body.source_refs if isinstance(r, dict)]
    support = [s for s in body.claims_deterministic_support if isinstance(s, dict)]
    sections = body.answer_sections if isinstance(body.answer_sections, dict) else {}
    reply = str(body.reply or "")

    supports_by_idx: dict[int, bool] = {}
    for row in support:
        if not isinstance(row, dict):
            continue
        idx = row.get("claim_index")
        ok = row.get("supported")
        if isinstance(idx, int) and isinstance(ok, bool):
            supports_by_idx[idx] = ok

    citations: list[dict[str, Any]] = []
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text") or "").strip()
        if not text:
            continue
        source = str(claim.get("source") or "unknown")
        supported = supports_by_idx.get(i)
        if supported is True:
            confidence = "high"
        elif source == "tool":
            confidence = "medium"
        else:
            confidence = "low"
        citations.append(
            {
                "claim_index": i,
                "text": text,
                "source": source,
                "supported": supported,
                "confidence_label": confidence,
            },
        )

    if citations:
        if all(c.get("supported") is True for c in citations):
            summary_conf = "high"
        elif any(c.get("source") == "tool" for c in citations):
            summary_conf = "medium"
        else:
            summary_conf = "low"
    else:
        summary_conf = "low"

    summary_text = str(sections.get("facts_from_tools") or sections.get("inferences") or reply)
    notes: list[str] = []
    if citations:
        supported_ct = sum(1 for c in citations if c.get("supported") is True)
        notes.append(f"{supported_ct}/{len(citations)} claims deterministically supported")
    if any(c.get("source") == "unknown" for c in citations):
        notes.append("contains unknown-source claims")

    return {
        "summary": summary_text,
        "confidence_label": summary_conf,
        "summary_confidence": {
            "level": summary_conf,
            "score": round(sum(1 for c in citations if c.get("supported") is True) / max(len(citations), 1), 3) if citations else 0.0,
            "notes": notes,
        },
        "claim_confidence_summary": {
            "high": sum(1 for c in citations if c.get("confidence_label") == "high"),
            "medium": sum(1 for c in citations if c.get("confidence_label") == "medium"),
            "low": sum(1 for c in citations if c.get("confidence_label") == "low"),
        },
        "citations": citations,
        "source_refs": refs,
        "trace_id": body.trace_id,
        "case_id": body.case_id,
        "turn_id": body.turn_id or "",
        "prompt_version": body.prompt_version or settings.copilot_prompt_version,
        "workflow_id": body.workflow_id,
        "persona": body.persona,
    }


@app.post("/v1/reports/case-summary")
async def case_summary_report(rb: CaseSummaryReportBody):
    """
    Render a case-summary PDF from client-supplied chat fields (same shape as POST /v1/chat response).
    Does not replay or store the conversation server-side.
    """
    _validate_scope_id("tenant_id", rb.tenant_id)
    _validate_scope_id("analyst_id", rb.analyst_id)
    if rb.case_id:
        _validate_scope_id("case_id", rb.case_id)
    if not is_analyst_allowed(rb.analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")
    pdf = render_case_summary_pdf(
        title=rb.title,
        reply=rb.reply,
        answer_sections=rb.answer_sections if isinstance(rb.answer_sections, dict) else {},
        claims=rb.claims,
        case_id=rb.case_id,
        turn_id=rb.turn_id,
        prompt_version=rb.prompt_version or settings.copilot_prompt_version,
        workflow_id=rb.workflow_id,
    )
    safe = re.sub(r"[^\w.-]+", "_", (rb.turn_id or "export").strip())[:48] or "export"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="case-summary-{safe}.pdf"'},
    )


@app.post("/v1/reports/turn-bundle")
async def turn_bundle_report(rb: TurnBundleReportBody):
    """
    Export Markdown + structured JSON for a single turn (paste from POST /v1/chat response).
    For review, Jira, or archival without relying on server-stored transcripts.
    """
    _validate_scope_id("tenant_id", rb.tenant_id)
    _validate_scope_id("analyst_id", rb.analyst_id)
    if rb.case_id:
        _validate_scope_id("case_id", rb.case_id)
    if not is_analyst_allowed(rb.analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")
    return _build_turn_bundle_payload(rb)


@app.get("/v1/governance")
async def governance_info():
    """Deployment AI governance profile (for UI banners and compliance packs). Not legal advice."""
    gov = normalize_governance_profile(settings.ai_governance_profile)
    return {
        "profile": gov,
        "label": governance_profile_label(gov),
        "references": governance_profile_references(gov),
        "batch_ttl_seconds": batch_store.ttl_seconds(),
        "disclaimer": ("Reference list is illustrative. Validate deployment against your counsel, DPA, and sector rules."),
    }


@app.post("/v1/batch/ingest")
async def batch_ingest(
    tenant_id: str = Form(...),
    analyst_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload CSV, JSON, NDJSON, or XLSX for copilot tabular tools (tenant + analyst scoped, in-memory TTL)."""
    _validate_scope_id("tenant_id", tenant_id)
    _validate_scope_id("analyst_id", analyst_id)
    if not is_analyst_allowed(analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")
    raw = await file.read()
    try:
        columns, rows, fmt = batch_store.parse_tabular_file(file.filename or "upload.csv", raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    batch_id = batch_store.store_batch(
        tenant_id,
        analyst_id,
        file.filename or "upload",
        columns,
        rows,
        fmt,
    )
    rec = batch_store.get_batch(batch_id, tenant_id, analyst_id)
    assert rec is not None
    prof = batch_store.batch_profile(rec)
    return {
        "batch_id": batch_id,
        "filename": prof.get("filename"),
        "format": prof.get("format"),
        "row_count": prof.get("row_count"),
        "columns": prof.get("columns"),
        "sample_rows": prof.get("sample_rows"),
        "limits": {
            "max_rows_stored": batch_store._MAX_ROWS,
            "max_file_mib": batch_store._MAX_FILE_BYTES // (1024 * 1024),
            "ttl_hours": batch_store.ttl_seconds() // 3600,
        },
    }


@app.post("/v1/knowledge/ingest")
async def knowledge_ingest(k: KnowledgeIngestBody, request: Request):
    _validate_scope_id("tenant_id", k.tenant_id)
    _validate_scope_id("analyst_id", k.analyst_id)
    if not is_analyst_allowed(k.analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")
    http = _http(request)
    use_emb = settings.copilot_knowledge_embeddings and bool(effective_embedding_api_key())
    try:
        doc_id = await knowledge_store.ingest_document_async(
            http,
            use_embeddings=use_emb,
            api_key=effective_embedding_api_key(),
            base_url=effective_embedding_base_url(),
            embed_model=settings.copilot_embedding_model,
            tenant_id=k.tenant_id,
            analyst_id=k.analyst_id,
            title=k.title,
            body=k.body,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "doc_id": doc_id,
        "title": k.title.strip()[:256] or "untitled",
        "ttl_hours": knowledge_store.ttl_seconds() // 3600,
        "docs_stored_for_scope": knowledge_store.count_docs(k.tenant_id, k.analyst_id),
        "embeddings_stored": use_emb,
    }


@app.post("/v1/feedback")
async def chat_feedback(fb: ChatFeedbackBody):
    tid = (fb.turn_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="turn_id required")
    tenant_id = (fb.tenant_id or "").strip()
    analyst_id = (fb.analyst_id or "").strip()
    if not tenant_id or not analyst_id:
        meta = feedback_store.lookup_turn(tid)
        if not meta:
            raise HTTPException(
                status_code=400,
                detail="tenant_id and analyst_id required when turn_id is unknown to this server",
            )
        tenant_id = str(meta["tenant_id"])
        analyst_id = str(meta["analyst_id"])
    _validate_scope_id("tenant_id", tenant_id)
    _validate_scope_id("analyst_id", analyst_id)
    if not is_analyst_allowed(analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")
    row_id = feedback_store.save_feedback(
        turn_id=tid,
        tenant_id=tenant_id,
        analyst_id=analyst_id,
        rating=fb.rating,
        note=fb.note,
        claim_indices=fb.claim_indices,
        tags=fb.tags,
    )
    copilot_analytics.schedule_feedback_submitted(
        settings,
        tenant_id=tenant_id,
        analyst_id=analyst_id,
        turn_id=tid,
        rating=int(fb.rating),
    )
    return {"ok": True, "stored": True, "feedback_id": row_id}


@app.get("/v1/feedback/summary")
async def feedback_summary(tenant_id: str, days: float = 7.0):
    _validate_scope_id("tenant_id", tenant_id)
    return feedback_store.feedback_summary(tenant_id, days=max(0.5, min(days, 365.0)))


@app.get("/v1/feedback/recent")
async def feedback_recent(tenant_id: str, limit: int = 50):
    _validate_scope_id("tenant_id", tenant_id)
    lim = max(1, min(limit, 200))
    return {"items": feedback_store.list_recent_feedback(tenant_id, lim)}


@app.post("/v1/review/turn")
async def turn_review_save(rv: TurnReviewBody):
    """Record human sign-off (approved / rejected) for a copilot turn_id (SQLite)."""
    tid = (rv.turn_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="turn_id required")
    _validate_scope_id("tenant_id", rv.tenant_id)
    _validate_scope_id("analyst_id", rv.analyst_id)
    if not is_analyst_allowed(rv.analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")
    meta = feedback_store.lookup_turn(tid)
    if meta and str(meta.get("tenant_id")) != rv.tenant_id.strip():
        raise HTTPException(status_code=400, detail="turn_id does not match tenant scope")
    row_id = review_store.save_review(
        turn_id=tid,
        tenant_id=rv.tenant_id.strip(),
        analyst_id=rv.analyst_id.strip(),
        status=rv.status,
        note=rv.note,
    )
    return {"ok": True, "stored": True, "review_id": row_id}


@app.get("/v1/review/turn")
async def turn_review_get(turn_id: str, tenant_id: str):
    _validate_scope_id("tenant_id", tenant_id)
    tid = (turn_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="turn_id required")
    row = review_store.latest_review(tid, tenant_id.strip())
    if not row:
        return {"found": False, "review": None}
    return {"found": True, "review": row}


@app.post("/v1/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """SSE: meta + deltas of final reply + final JSON tail (use POST /v1/chat for full sync payload)."""

    async def events():
        out = await _build_chat_response(body, request)
        meta = {
            "turn_id": out.get("turn_id"),
            "prompt_version": out.get("prompt_version"),
            "persona": out.get("persona"),
            "workflow_id": out.get("workflow_id"),
            "warning": out.get("warning"),
        }
        yield f"data: {json.dumps({'type': 'meta', 'payload': meta})}\n\n"
        yield f"data: {json.dumps({'type': 'tool_calls', 'payload': {'count': len(out.get('tool_calls') or [])}})}\n\n"
        reply = out.get("reply") or ""
        step = 100
        for i in range(0, len(reply), step):
            yield f"data: {json.dumps({'type': 'delta', 'payload': {'text': reply[i : i + step]}})}\n\n"
        essentials = {
            k: out[k]
            for k in (
                "turn_id",
                "prompt_version",
                "persona",
                "workflow_id",
                "workflow_params",
                "claims",
                "source_refs",
                "answer_sections",
                "claims_deterministic_support",
                "tool_acknowledgment_warnings",
                "judge_assessments",
                "judge_error",
                "evidence_bundle_draft",
                "playbook_id",
                "claims_warning",
                "claims_grounding_adjustments",
                "injection_sanitized",
                "tool_calls",
                "derived_facts",
                "assurance_refused",
                "assurance_violations",
                "turn_metrics",
            )
            if k in out
        }
        essentials["tool_calls_count"] = len(out.get("tool_calls") or [])
        yield f"data: {json.dumps({'type': 'final', 'payload': essentials})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/chat")
async def chat(body: ChatRequest, request: Request):
    return await _build_chat_response(body, request)


async def _build_chat_response(body: ChatRequest, request: Request) -> dict[str, Any]:
    _validate_scope_id("tenant_id", body.tenant_id)
    _validate_scope_id("analyst_id", body.analyst_id)
    if body.case_id:
        _validate_scope_id("case_id", body.case_id)
    if body.batch_id:
        _validate_scope_id("batch_id", body.batch_id)
        try:
            batch_store.validate_batch_id(body.batch_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    active_playbook: str | None = None
    if body.playbook_id:
        _validate_scope_id("playbook_id", body.playbook_id)
        try:
            active_playbook = validate_playbook_id(body.playbook_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    active_workflow: str | None = None
    workflow_params_norm: dict[str, Any] = {}
    if body.workflow_id:
        try:
            active_workflow = validate_workflow_id(body.workflow_id.strip())
            workflow_params_norm = normalize_workflow_params(body.workflow_params)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if not is_analyst_allowed(body.analyst_id):
        raise HTTPException(status_code=403, detail="Analyst not permitted for this deployment")

    max_msgs = settings.copilot_max_chat_messages
    if len(body.messages) > max_msgs:
        raise HTTPException(400, f"Too many messages in conversation (max {max_msgs})")

    if body.platform_audit is not None and len(body.platform_audit) > _MAX_AUDIT_EVENTS:
        raise HTTPException(400, f"platform_audit exceeds max {_MAX_AUDIT_EVENTS} events")

    http = _http(request)

    system = build_copilot_system_prompt(body.persona)

    opts = body.context_options or CopilotContextOptions()
    audit_events: list[dict[str, Any]] = []
    if opts.track_historical_actions:
        audit_events = _normalize_platform_audit_rows(
            list(body.platform_audit) if body.platform_audit else None,
        )
        if opts.skip_session_actions:
            audit_events = _filter_session_noise_audit(audit_events)
        audit_events = audit_events[:_MAX_AUDIT_EVENTS]

    ctx_notes: list[str] = []
    if opts.track_historical_actions and opts.only_session:
        ctx_notes.append(
            "Analyst UI scoped platform audit to the current browser session window (since session start); older tenant activity may be omitted from the slice."
        )
    if opts.track_historical_actions and opts.skip_session_actions:
        ctx_notes.append("Copilot/session-navigation noise rows were excluded from the audit slice where applicable.")
    if ctx_notes:
        system += "\n\nCONTEXT OPTIONS (analyst preferences; audit slice may be filtered accordingly):\n"
        system += "\n".join(f"- {n}" for n in ctx_notes)

    audit_block = ""
    if settings.copilot_include_platform_audit_in_prompt:
        audit_block = _format_platform_audit_for_prompt(audit_events)
    if audit_block:
        system = system + "\n\n" + audit_block

    gov_prof = normalize_governance_profile(settings.ai_governance_profile)
    system += regional_system_prompt_append(gov_prof)

    if active_playbook:
        system += playbook_system_append(active_playbook)
        system += f"\nThe analyst selected playbook **{active_playbook}**. Follow it unless the user explicitly redirects; still ground answers in tools.\n"

    if active_workflow:
        system += format_workflow_system_append(active_workflow, workflow_params_norm)

    if settings.copilot_reference_mode:
        system += "\n\n" + REFERENCE_MODE_SYSTEM_APPEND

    if settings.copilot_structured_sections:
        system = system.replace(
            "CLAIMS TRAILER (REQUIRED for every assistant turn):",
            structured_sections_prompt_block() + "CLAIMS TRAILER (REQUIRED for every assistant turn):",
        )

    messages = []
    injection_detected = False
    for m in body.messages:
        if m.role not in ("user", "assistant"):
            continue
        if m.role == "user":
            if _detect_injection(m.content):
                injection_detected = True
            messages.append({"role": m.role, "content": _sanitize_message(m.content)})
        else:
            # Assistant history is untrusted (UI may replay model output); sanitize like user text.
            messages.append({"role": m.role, "content": _sanitize_message(m.content)})

    if injection_detected and settings.copilot_injection_policy == "reject":
        tid = str(uuid.uuid4())
        blk_claims = [
            {
                "text": "Request blocked: potential prompt-injection patterns; no tools executed.",
                "source": "unknown",
            },
        ]
        feedback_store.record_turn(
            turn_id=tid,
            tenant_id=body.tenant_id,
            analyst_id=body.analyst_id,
            case_id=body.case_id,
            playbook_id=active_playbook,
            prompt_version=settings.copilot_prompt_version,
            reply_preview="[injection_reject]",
            tool_count=0,
            persona=body.persona,
            workflow_id=active_workflow,
        )
        copilot_analytics.schedule_turn_completed(
            settings,
            tenant_id=body.tenant_id,
            analyst_id=body.analyst_id,
            turn_id=tid,
            tool_invocation_count=0,
            assurance_mode=settings.copilot_assurance_mode,
            had_tool_error=False,
            assurance_refused=False,
            persona=body.persona,
        )
        return {
            "reply": ("I detected a potential prompt injection attempt. I can only assist with fraud investigations using my available tools."),
            "tool_calls": [],
            "claims": blk_claims,
            "source_refs": [],
            "warning": "injection_detected",
            "turn_id": tid,
            "persona": body.persona,
            "workflow_id": active_workflow,
            "workflow_params": workflow_params_norm if active_workflow else None,
            "prompt_version": settings.copilot_prompt_version,
            "answer_sections": {"sections_found": []},
            "claims_deterministic_support": deterministic_claim_support(blk_claims, []),
            "evidence_bundle_draft": build_evidence_bundle_draft(
                reply="[blocked]",
                claims=blk_claims,
                source_refs=[],
                answer_sections={},
                claims_analysis=[],
                tool_calls=[],
                prompt_version=settings.copilot_prompt_version,
                playbook_id=active_playbook,
                turn_id=tid,
                bundle_format=settings.copilot_evidence_bundle_format,
                contract_version=INTEGRATION_CONTRACT_VERSION,
                agent_build=(settings.agent_build_id or "").strip(),
                redaction_level=settings.copilot_evidence_redaction_level,
            ),
        }

    if body.case_id and messages:
        messages[-1]["content"] += f"\n\n[Context: current case_id is {body.case_id}]"
    if body.batch_id and messages:
        messages[-1]["content"] += f"\n\n[Context: active batch_id for tabular tools is {body.batch_id.strip()}]"

    disabled = effective_disabled_tools(settings)
    reviewer_secret = (settings.copilot_reviewer_secret or "").strip()
    sensitive = parse_sensitive_tools(settings.copilot_sensitive_tools)
    if sensitive and reviewer_secret:
        if request.headers.get("x-reviewer-secret", "") != reviewer_secret:
            disabled = frozenset(disabled | sensitive)
    active_tool_defs = filter_tool_definitions(TOOL_DEFINITIONS, disabled)
    if settings.copilot_plain_chat:
        active_tool_defs = []
    if not active_tool_defs:
        system = await _maybe_prefetch_rag_to_system(
            http,
            system,
            messages,
            body.tenant_id,
            body.analyst_id,
        )

    raw_reply, tool_calls, usage_merged, llm_rounds = await _llm_tool_loop(
        http,
        system,
        messages,
        body.tenant_id,
        body.analyst_id,
        active_tool_defs,
    )

    prose, claims, claims_warn = _parse_tarka_claims_reply(raw_reply)
    reply = _validate_output(prose)

    grounding_adj: list[str] = []
    if settings.copilot_enforce_tool_claim_grounding:
        claims, grounding_adj = enforce_tool_claim_grounding(claims, tool_calls)

    tool_names = [t.get("tool") for t in tool_calls if isinstance(t, dict)]
    tool_errors = sum(1 for t in tool_calls if isinstance(t, dict) and isinstance(t.get("result"), dict) and (t.get("result") or {}).get("error"))
    tn_non_null = [str(x) for x in tool_names if x]
    distinct_tools = len(set(tn_non_null))
    tool_repeat_count = max(0, len(tn_non_null) - distinct_tools)
    try:
        m = get_metrics()
        m.inc("investigation_agent_chats_total")
        m.inc("investigation_agent_tool_calls_total", len(tool_calls))
        m.inc("investigation_agent_tool_error_results_total", tool_errors)
        pkey = body.persona if body.persona in ("investigation", "orchestrator") else "investigation"
        m.inc(f"investigation_agent_chats_persona_{pkey}_total")
    except Exception:
        pass
    log.info(
        "%s",
        json.dumps(
            {
                "event": "investigation_tool_quality",
                "tenant_id": body.tenant_id,
                "analyst_id": body.analyst_id,
                "case_id": body.case_id,
                "persona": body.persona,
                "tool_count": len(tool_calls),
                "tool_error_count": tool_errors,
                "distinct_tool_names": distinct_tools,
                "tool_repeat_count": tool_repeat_count,
                "tools": tool_names,
                "model": _effective_chat_model(),
            },
            default=str,
        ),
    )

    source_refs = build_source_reference_cards(tool_calls)
    turn_id = str(uuid.uuid4())
    answer_sections = parse_structured_sections(reply)
    det_support = deterministic_claim_support(claims, tool_calls)
    ack_warns = tool_error_acknowledgment_warnings(reply, tool_calls)

    derived_facts: list[dict[str, Any]] = []
    if settings.copilot_derived_facts or settings.copilot_assurance_mode == "strict":
        derived_facts = extract_derived_facts(tool_calls)

    assurance_refused = False
    assurance_violations: list[str] = []
    if settings.copilot_assurance_mode == "strict":
        assurance_violations = strict_assurance_violations(
            claims=claims,
            det_support=det_support,
            ack_warns=ack_warns,
        )
        if assurance_violations:
            assurance_refused = True
            reply = format_assurance_refusal(assurance_violations)
            claims = [{"text": reply, "source": "unknown"}]
            answer_sections = parse_structured_sections(reply)
            det_support = deterministic_claim_support(claims, tool_calls)
            ack_warns = []
            grounding_adj = []

    judge_assessments = None
    judge_error: str | None = None
    if not assurance_refused and settings.copilot_enable_judge_pass and settings.openai_api_key:
        jm = (settings.openai_judge_model or "").strip() or _effective_chat_model()
        ja, jerr = await llm_judge_claim_support(
            http,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=jm,
            max_tokens=settings.copilot_judge_max_tokens,
            claims=claims,
            tool_calls=tool_calls,
        )
        judge_error = jerr
        if isinstance(ja, dict):
            judge_assessments = ja.get("assessments")

    tool_surface = "plain" if not active_tool_defs else "tools"
    out: dict[str, Any] = {
        "reply": reply,
        "tool_calls": tool_calls,
        "claims": claims,
        "source_refs": source_refs,
        "turn_id": turn_id,
        "persona": body.persona,
        "prompt_version": settings.copilot_prompt_version,
        "answer_sections": answer_sections,
        "claims_deterministic_support": det_support,
        "turn_metrics": {
            "model": _effective_chat_model(),
            "llm_completion_rounds": llm_rounds,
            "tool_surface": tool_surface,
            "usage": usage_merged,
        },
        "evidence_bundle_draft": build_evidence_bundle_draft(
            reply=reply,
            claims=claims,
            source_refs=source_refs,
            answer_sections=answer_sections,
            claims_analysis=det_support,
            tool_calls=tool_calls,
            prompt_version=settings.copilot_prompt_version,
            playbook_id=active_playbook,
            turn_id=turn_id,
            bundle_format=settings.copilot_evidence_bundle_format,
            contract_version=INTEGRATION_CONTRACT_VERSION,
            agent_build=(settings.agent_build_id or "").strip(),
            redaction_level=settings.copilot_evidence_redaction_level,
        ),
    }
    if active_playbook:
        out["playbook_id"] = active_playbook
    if active_workflow:
        out["workflow_id"] = active_workflow
        out["workflow_params"] = workflow_params_norm
    if claims_warn:
        out["claims_warning"] = claims_warn
    if grounding_adj:
        out["claims_grounding_adjustments"] = grounding_adj
    if ack_warns:
        out["tool_acknowledgment_warnings"] = ack_warns
    if judge_assessments is not None:
        out["judge_assessments"] = judge_assessments
    if judge_error:
        out["judge_error"] = judge_error
    if injection_detected and settings.copilot_injection_policy == "sanitize":
        out["injection_sanitized"] = True
    if derived_facts:
        out["derived_facts"] = derived_facts
    if settings.copilot_assurance_mode == "strict":
        out["assurance_mode"] = "strict"
        if assurance_refused:
            out["assurance_refused"] = True
            out["assurance_violations"] = assurance_violations
    copilot_analytics.schedule_turn_completed(
        settings,
        tenant_id=body.tenant_id,
        analyst_id=body.analyst_id,
        turn_id=turn_id,
        tool_invocation_count=len(tool_calls),
        assurance_mode=settings.copilot_assurance_mode,
        had_tool_error=tool_errors > 0,
        assurance_refused=assurance_refused,
        persona=body.persona,
    )
    feedback_store.record_turn(
        turn_id=turn_id,
        tenant_id=body.tenant_id,
        analyst_id=body.analyst_id,
        case_id=body.case_id,
        playbook_id=active_playbook,
        prompt_version=settings.copilot_prompt_version,
        reply_preview=reply[:1800],
        tool_count=len(tool_calls),
        persona=body.persona,
        workflow_id=active_workflow,
    )
    return out
