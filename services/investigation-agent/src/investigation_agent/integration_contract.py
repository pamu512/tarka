from __future__ import annotations
from typing import Any

from investigation_agent.config import Settings
from investigation_agent.copilot_hardening import filter_tool_definitions, parse_disabled_tools, parse_sensitive_tools
from investigation_agent.tools import TOOL_DEFINITIONS

"""
Logical integration contract for the investigation copilot.

Exposes a versioned, machine-readable snapshot of which upstream services are configured
and which tools are registered—used for adapter parity checks and Saarthi Pro positioning
("maintained adapter" against a declared profile).

Does not expose raw URLs (avoid leaking internal endpoints in health responses).
"""
# Bump when tool names, families, or upstream semantics change in a breaking way for adapters.
INTEGRATION_CONTRACT_VERSION = "1.2.0"

# Logical families for mapping third-party stacks → OSS tool surface.
_TOOL_FAMILY: dict[str, str] = {
    "get_case": "case",
    "list_cases": "case",
    "subgraph": "graph",
    "get_entity_tags": "graph",
    "get_entity_velocity": "decision",
    "get_decision_audit": "decision",
    "subgraph_with_velocity": "graph",
    "export_outcome_labeled_dataset": "labels",
    "ingest_labeled_rows": "labels",
    "get_stored_labeled_dataset": "labels",
    "get_batch_profile": "batch",
    "query_batch_rows": "batch",
    "aggregate_batch_column": "batch",
    "search_knowledge": "knowledge",
    "compare_entity_queue_snapshot": "case",
    "run_replay_ab_comparison": "replay",
}


def runtime_suppressed_tools(settings: Settings) -> frozenset[str]:
    """
    Tools that cannot succeed until upstream base URLs are set.
    Used when copilot_hide_tools_without_upstream is true.
    """
    if not settings.copilot_hide_tools_without_upstream:
        return frozenset()
    out: set[str] = set()
    case_ok = bool((settings.case_api_url or "").strip())
    decision_ok = bool((settings.decision_api_url or "").strip())
    graph_ok = bool((settings.graph_service_url or "").strip())
    if not case_ok:
        out.update(
            {
                "get_case",
                "list_cases",
                "export_outcome_labeled_dataset",
                "ingest_labeled_rows",
                "get_stored_labeled_dataset",
            },
        )
    if not decision_ok:
        out.update(
            {
                "get_entity_velocity",
                "get_decision_audit",
                "run_replay_ab_comparison",
            },
        )
    if not graph_ok:
        out.update({"subgraph", "get_entity_tags", "subgraph_with_velocity"})
    if not decision_ok or not case_ok:
        out.add("compare_entity_queue_snapshot")
    return frozenset(out)


def effective_disabled_tools(settings: Settings) -> frozenset[str]:
    """Env disabled tools union runtime upstream suppression."""
    env = parse_disabled_tools(settings.copilot_disabled_tools)
    return frozenset(env | runtime_suppressed_tools(settings))


def _tool_names_from_definitions() -> list[str]:
    out: list[str] = []
    for d in TOOL_DEFINITIONS:
        fn = (d.get("function") or {}).get("name")
        if isinstance(fn, str) and fn.strip():
            out.append(fn.strip())
    return out


def build_integration_snapshot(
    settings: Settings,
    *,
    disabled_tools: frozenset[str],
) -> dict[str, Any]:
    """
    Build a JSON-serializable snapshot for GET /v1/integration and health.integration.

    `disabled_tools` should be **effective** disabled set (env + upstream suppression), usually
    from `effective_disabled_tools(settings)`. Per-request sensitive-tool hiding is reported separately.
    """
    all_names = _tool_names_from_definitions()
    active_defs = filter_tool_definitions(TOOL_DEFINITIONS, disabled_tools)
    enabled_names: list[str] = []
    for d in active_defs:
        fn = (d.get("function") or {}).get("name")
        if isinstance(fn, str) and fn.strip():
            enabled_names.append(fn.strip())

    case_url = (settings.case_api_url or "").strip()
    decision_url = (settings.decision_api_url or "").strip()
    graph_url = (settings.graph_service_url or "").strip()

    families_enabled: dict[str, list[str]] = {}
    for name in enabled_names:
        fam = _TOOL_FAMILY.get(name, "other")
        families_enabled.setdefault(fam, []).append(name)

    sensitive = parse_sensitive_tools(settings.copilot_sensitive_tools)
    reviewer_on = bool((settings.copilot_reviewer_secret or "").strip())

    upstream_suppressed = sorted(runtime_suppressed_tools(settings)) if settings.copilot_hide_tools_without_upstream else []

    return {
        "contract_version": INTEGRATION_CONTRACT_VERSION,
        "profile_id": (settings.integration_profile_id or "tarka_reference_v1").strip(),
        "upstream_configured": {
            "case_api": bool(case_url),
            "decision_api": bool(decision_url),
            "graph_service": bool(graph_url),
        },
        "upstream_runtime_notes": {
            "graph_tools_return_error_if_unconfigured": True,
            "decision_tools_return_error_if_unconfigured": True,
            "hide_tools_without_upstream": bool(settings.copilot_hide_tools_without_upstream),
            "tool_error_shape": {
                "required": ["error", "code", "message", "severity", "retryable", "upstream"],
                "severity_values": ["warning", "error"],
            },
        },
        "tools": {
            "registered_total": len(all_names),
            "enabled_count": len(enabled_names),
            "enabled": enabled_names,
            "disabled_effective": sorted(disabled_tools),
            "upstream_suppressed": upstream_suppressed,
        },
        "families_enabled": {k: sorted(v) for k, v in sorted(families_enabled.items())},
        "maker_checker": {
            "reviewer_secret_configured": reviewer_on,
            "sensitive_tool_names": sorted(sensitive),
            "note": "When reviewer_secret_configured, sensitive tools are omitted from the model unless x-reviewer-secret matches.",
        },
    }
