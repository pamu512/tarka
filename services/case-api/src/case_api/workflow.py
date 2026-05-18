from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

"""Workflow engine for case automation.

Workflows are defined as JSON and stored in a workflows/ directory.
Each workflow has triggers, conditions, and actions.

Trigger types:
  - case_created     — fires when a new case is created
  - case_updated     — fires when a case status changes
  - decision_deny    — fires when a fraud decision is "deny"
  - decision_review  — fires when a fraud decision is "review"
  - sla_breach       — fires when a case exceeds its SLA timer

Action types:
  - assign_team      — route the case to a specific team
  - set_priority     — override the case priority
  - add_label        — add labels to the case
  - send_webhook     — fire an outbound HTTP POST
  - escalate         — change status to "escalated"
  - add_comment      — auto-add a system comment
"""
log = logging.getLogger("case-api.workflow")

_workflows: list[dict[str, Any]] = []


def load_workflows(path: str = "./workflows") -> None:
    global _workflows
    d = Path(path)
    if not d.is_dir():
        _workflows = []
        return
    loaded: list[dict[str, Any]] = []
    for f in sorted(d.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            if wf.get("enabled", True):
                loaded.append(wf)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("skipping workflow %s: %s", f, e)
    _workflows = loaded
    log.info("loaded %d workflows from %s", len(loaded), d)


def get_workflows() -> list[dict[str, Any]]:
    return list(_workflows)


class WorkflowContext:
    """Data available to workflow conditions and actions."""

    def __init__(
        self,
        trigger: str,
        case: dict[str, Any],
        decision: dict[str, Any] | None = None,
    ) -> None:
        self.trigger = trigger
        self.case = case
        self.decision = decision or {}
        self.actions_executed: list[dict[str, Any]] = []
        self.mutations: dict[str, Any] = {}


def _evaluate_condition(ctx: WorkflowContext, cond: dict[str, Any]) -> bool:
    field = cond.get("field", "")
    op = cond.get("op", "eq")
    value = cond.get("value")

    actual = ctx.case.get(field) if field in ctx.case else ctx.decision.get(field)

    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "gte":
        return actual is not None and float(actual) >= float(value)
    if op == "lte":
        return actual is not None and float(actual) <= float(value)
    if op == "in":
        return actual in (value or [])
    if op == "contains":
        return isinstance(actual, (list, str)) and value in actual
    if op == "has_tag":
        tags = ctx.case.get("labels", []) or ctx.decision.get("tags", [])
        return value in tags
    return False


async def _execute_action(
    ctx: WorkflowContext,
    action: dict[str, Any],
    http: httpx.AsyncClient | None = None,
) -> None:
    action_type = action.get("type", "")

    if action_type == "assign_team":
        ctx.mutations["assigned_team"] = action.get("team", "default")
        ctx.actions_executed.append({"type": "assign_team", "team": action.get("team")})

    elif action_type == "set_priority":
        ctx.mutations["priority"] = action.get("priority", "high")
        ctx.actions_executed.append({"type": "set_priority", "priority": action.get("priority")})

    elif action_type == "add_label":
        labels = list(ctx.case.get("labels", []) or [])
        new_labels = action.get("labels", [])
        ctx.mutations["labels"] = sorted(set(labels) | set(new_labels))
        ctx.actions_executed.append({"type": "add_label", "labels": new_labels})

    elif action_type == "escalate":
        ctx.mutations["status"] = "escalated"
        ctx.mutations["priority"] = "critical"
        ctx.actions_executed.append({"type": "escalate"})

    elif action_type == "add_comment":
        ctx.mutations.setdefault("_comments", []).append(
            {
                "author": "workflow-engine",
                "body": action.get("message", "Auto-comment from workflow"),
            }
        )
        ctx.actions_executed.append({"type": "add_comment", "message": action.get("message")})

    elif action_type == "send_webhook":
        url = action.get("url", "")
        if url and http:
            payload = {
                "trigger": ctx.trigger,
                "case": ctx.case,
                "decision": ctx.decision,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await http.post(url, json=payload, timeout=5.0)
                ctx.actions_executed.append({"type": "send_webhook", "url": url, "status": "sent"})
            except Exception as e:
                log.warning("webhook failed for %s: %s", url, e)
                ctx.actions_executed.append(
                    {"type": "send_webhook", "url": url, "status": "failed", "error": str(e)}
                )
    else:
        log.warning("unknown action type: %s", action_type)


async def evaluate_workflows(
    trigger: str,
    case: dict[str, Any],
    decision: dict[str, Any] | None = None,
    http: httpx.AsyncClient | None = None,
) -> WorkflowContext:
    """Run all matching workflows for a given trigger. Returns context with mutations."""
    ctx = WorkflowContext(trigger=trigger, case=case, decision=decision)

    for wf in _workflows:
        wf_triggers = wf.get("triggers", [])
        if trigger not in wf_triggers:
            continue

        conditions = wf.get("conditions", [])
        if conditions and not all(_evaluate_condition(ctx, c) for c in conditions):
            continue

        for action in wf.get("actions", []):
            await _execute_action(ctx, action, http)

    return ctx


def compute_sla_deadline(
    priority: str,
    created_at: datetime | None = None,
    *,
    sla_hours_override: int | None = None,
) -> datetime:
    """Returns the SLA deadline based on priority, or ``sla_hours_override`` when set (1–8760)."""
    base = created_at or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if sla_hours_override is not None and int(sla_hours_override) > 0:
        hours = int(sla_hours_override)
    else:
        sla_hours = {"critical": 1, "high": 4, "medium": 24, "low": 72}
        hours = sla_hours.get(priority, 24)
    return base + timedelta(hours=hours)


def is_sla_breached_at(
    priority: str,
    created_at: datetime,
    *,
    sla_hours_override: int | None = None,
    as_of: datetime | None = None,
) -> bool:
    """Whether SLA is breached as of ``as_of`` (default: current UTC time)."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    deadline = compute_sla_deadline(priority, created_at, sla_hours_override=sla_hours_override)
    ref = as_of or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return ref > deadline


def is_sla_breached(
    priority: str,
    created_at: datetime,
    *,
    sla_hours_override: int | None = None,
) -> bool:
    return is_sla_breached_at(
        priority, created_at, sla_hours_override=sla_hours_override, as_of=None
    )
