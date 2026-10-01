"""Desk residual-review hook. Empty Jev URL does not prefetch and does not call out."""

from __future__ import annotations

from typing import Any

import httpx

from investigation_agent import config
from investigation_agent.tools import tool_get_case, tool_get_decision_audit, tool_subgraph
from jev_system_one.client import SystemOneClient
from jev_system_one.pack import build_evidence_pack
from jev_system_one.policy import AdviseDecision, decide_advise, preflight_advise
from jev_system_one.questions import PACK_ID, build_systemone_request

_ABSTAIN_COPY = {
    "thin_evidence": (
        "Residual review note withheld: the evidence pack is too thin "
        "(no leftover body and no evaluate receipt)."
    ),
    "abstain": (
        "Residual review note withheld: the confidence gate would skip a generative note on this pack."
    ),
    "jev_error": "Residual review note withheld: the confidence check failed closed.",
    "jev_auth": "Residual review note withheld: the confidence check failed authentication.",
    "skip_llm": "Residual review note withheld: the confidence check failed closed.",
}


def abstain_reply(gate: str) -> str:
    return _ABSTAIN_COPY.get(gate, _ABSTAIN_COPY["jev_error"])


def _pass_through() -> AdviseDecision:
    return AdviseDecision(call_jev=False, call_llm=True, gate="off", receipt=None)


async def _load_case(
    http: httpx.AsyncClient, case_id: str, tenant_id: str, analyst_id: str
) -> dict[str, Any] | None:
    try:
        got = await tool_get_case(http, case_id, tenant_id, analyst_id)
    except Exception:
        return None
    if not isinstance(got, dict):
        return None
    case = got.get("case")
    return case if isinstance(case, dict) else None


async def _load_audit(
    http: httpx.AsyncClient, trace_id: str, tenant_id: str, analyst_id: str
) -> dict[str, Any] | None:
    if not trace_id:
        return None
    try:
        got = await tool_get_decision_audit(http, trace_id, tenant_id, analyst_id)
    except Exception:
        return None
    if not isinstance(got, dict) or got.get("error"):
        return None
    audit = got.get("audit")
    return audit if isinstance(audit, dict) else None


async def _load_graph(
    http: httpx.AsyncClient, entity_id: str, tenant_id: str, analyst_id: str
) -> dict[str, Any] | None:
    if not entity_id or not (config.settings.graph_service_url or "").strip():
        return None
    try:
        got = await tool_subgraph(http, entity_id, tenant_id, analyst_id, depth=1)
    except Exception:
        return None
    return got if isinstance(got, dict) and not got.get("error") else None


async def run_residual_confidence_gate(
    *,
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    case_id: str | None,
) -> AdviseDecision:
    """Judge a residual case review before the first generative Advise round.

    No ``case_id`` means this is not a residual review: today's path, no HTTP.
    Empty ``JEV_SYSTEM_ONE_URL`` or ``JEV_MODE=off`` is the same.
    """
    url = (config.settings.jev_system_one_url or "").strip()
    mode = (config.settings.jev_mode or "").strip()
    api_key = (config.settings.jev_api_key or "").strip()
    api_key_required = bool(config.settings.jev_api_key_required)
    if not (case_id or "").strip() or not url or mode == "off":
        return _pass_through()
    if mode not in ("shadow", "gate"):
        blocked = preflight_advise(
            url=url,
            mode=mode,
            pack=None,
            api_key=api_key,
            api_key_required=api_key_required,
        )
        return blocked if blocked is not None else _pass_through()

    if api_key_required and not api_key:
        blocked = preflight_advise(
            url=url,
            mode=mode,
            pack={"leftover": {"case_id": case_id}},
            api_key=api_key,
            api_key_required=True,
        )
        return blocked if blocked is not None else _pass_through()

    question_pack = (config.settings.jev_question_pack or PACK_ID).strip() or PACK_ID
    if question_pack != PACK_ID:
        blocked = preflight_advise(
            url=url,
            mode=mode,
            pack={"leftover": {"case_id": case_id}},
            question_pack=question_pack,
            api_key=api_key,
            api_key_required=api_key_required,
        )
        return blocked if blocked is not None else _pass_through()

    case = await _load_case(http, case_id.strip(), tenant_id, analyst_id)
    trace_id = ""
    entity_id = ""
    if isinstance(case, dict):
        trace_id = str(case.get("trace_id") or "").strip()
        entity_id = str(case.get("entity_id") or "").strip()
    audit = await _load_audit(http, trace_id, tenant_id, analyst_id)
    graph = await _load_graph(http, entity_id, tenant_id, analyst_id)
    pack = build_evidence_pack(
        tenant_id=tenant_id,
        case=case,
        audit=audit,
        graph=graph,
    )
    pre = preflight_advise(
        url=url,
        mode=mode,
        pack=pack,
        question_pack=question_pack,
        api_key=api_key,
        api_key_required=api_key_required,
    )
    if pre is not None:
        return pre

    client = SystemOneClient(
        base_url=url,
        api_key=api_key,
        timeout_ms=int(config.settings.jev_timeout_ms),
    )
    judgment = await client.judge(build_systemone_request(pack))
    return decide_advise(
        mode=mode,
        min_confidence=float(config.settings.jev_min_confidence),
        judgment=judgment,
    )
