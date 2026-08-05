"""Platform enforcement adapters — block / step_up / allow (Wave D).

Invoked from ``DecisionOutcomeHandler``. Does not create investigation cases;
case-api remains a separate outcome path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

log = logging.getLogger("decision-api.enforcement")

ENFORCEMENT_JOURNAL_SCHEMA = "tarka.enforcement_delivery/v1"

EnforcementAction = Literal["allow", "step_up", "block"]

ENFORCEMENT_SCHEMA = "tarka.enforcement/v1"

_STEP_UP_ACTIONS = frozenset(
    {
        "step_up_mfa",
        "step_up_attestation",
        "step_up_auth",
        "challenge",
        "step_up",
        "step-up",
        "step-up-mfa",
        "step-up-attestation",
    }
)

MetricsInc = Callable[..., Any]


@dataclass(frozen=True)
class EnforcementIntent:
    action: EnforcementAction
    decision: str
    recommended_action: str | None


def is_step_up_recommended(recommended_action: str | None) -> bool:
    """True when recommended_action is a step-up / challenge class hint."""
    rec = (recommended_action or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not rec:
        return False
    return (
        rec in _STEP_UP_ACTIONS
        or rec.startswith("step_up")
        or rec.startswith("challenge")
    )


def resolve_enforcement_action(
    decision: str,
    recommended_action: str | None = None,
) -> EnforcementAction:
    """Map evaluate outcome → platform enforcement verb."""
    d = (decision or "").strip().lower()
    if d == "deny":
        return "block"
    if is_step_up_recommended(recommended_action):
        return "step_up"
    return "allow"


def resolve_enforcement_intent(
    decision: str,
    recommended_action: str | None = None,
) -> EnforcementIntent:
    return EnforcementIntent(
        action=resolve_enforcement_action(decision, recommended_action),
        decision=(decision or "").strip().lower(),
        recommended_action=recommended_action,
    )


def enforcement_webhook_configured() -> bool:
    return bool(os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_URL", "").strip())


def enforcement_journal_path() -> Path:
    override = os.environ.get("TARKA_ENFORCEMENT_JOURNAL_PATH", "").strip()
    if override:
        return Path(override)
    try:
        from decision_api.config import settings

        return Path(settings.rules_path) / "enforcement_delivery.jsonl"
    except Exception:
        return Path("./rules") / "enforcement_delivery.jsonl"


def append_enforcement_journal(record: dict[str, Any]) -> None:
    """Append-only delivery journal (ack / fail / skipped). Fail soft."""
    path = enforcement_journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        log.debug("enforcement_journal_append_failed", exc_info=True)


def enforcement_journal_line_count() -> int:
    path = enforcement_journal_path()
    if not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def read_enforcement_journal(limit: int = 50) -> list[dict[str, Any]]:
    """Return newest journal records (tail), oldest-first within the window."""
    path = enforcement_journal_path()
    lim = max(1, min(int(limit), 500))
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for ln in lines[-lim:]:
        try:
            row = json.loads(ln)
            if isinstance(row, dict):
                out.append(row)
        except json.JSONDecodeError:
            continue
    return out


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _build_payload(
    *,
    intent: EnforcementIntent,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    score: float,
    tags: list[str],
    challenge_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_id": ENFORCEMENT_SCHEMA,
        "enforcement_action": intent.action,
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "event_type": event_type,
        "decision": intent.decision,
        "recommended_action": intent.recommended_action,
        "score": score,
        "tags": list(tags),
        "challenge_metadata": challenge_metadata or {},
    }


async def apply_enforcement_adapters(
    *,
    http: Any,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    decision: str,
    score: float,
    tags: list[str],
    recommended_action: str | None = None,
    challenge_metadata: dict[str, Any] | None = None,
    metrics_inc: MetricsInc | None = None,
) -> dict[str, Any]:
    """Emit enforcement metrics and optional tenant webhook for allow/step_up/block.

    Fail soft: webhook/metric errors are logged; never raises into evaluate.
    """
    intent = resolve_enforcement_intent(decision, recommended_action)
    summary: dict[str, Any] = {
        "enforcement_action": intent.action,
        "webhook": None,
    }

    if metrics_inc is not None:
        try:
            metrics_inc(f"tarka_enforcement_{intent.action}_total", trace_id=trace_id)
            metrics_inc("tarka_enforcement_total", trace_id=trace_id)
        except TypeError:
            try:
                metrics_inc(f"tarka_enforcement_{intent.action}_total")
                metrics_inc("tarka_enforcement_total")
            except Exception:
                log.debug("enforcement_metric_failed", exc_info=True)
        except Exception:
            log.debug("enforcement_metric_failed", exc_info=True)

    url = os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_URL", "").strip()
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    base_journal: dict[str, Any] = {
        "schema_id": ENFORCEMENT_JOURNAL_SCHEMA,
        "ts": ts,
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "enforcement_action": intent.action,
        "decision": intent.decision,
        "recommended_action": intent.recommended_action,
    }

    if not url:
        append_enforcement_journal(
            {**base_journal, "status": "skipped", "reason": "webhook_unset"}
        )
        summary["journal"] = {"status": "skipped"}
        return summary

    payload = _build_payload(
        intent=intent,
        trace_id=trace_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        event_type=event_type,
        score=score,
        tags=tags,
        challenge_metadata=challenge_metadata
        if isinstance(challenge_metadata, dict)
        else None,
    )
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "x-tarka-enforcement-event": intent.action,
    }
    secret = os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_SECRET", "").strip()
    if secret:
        headers["x-tarka-signature"] = _sign(raw, secret)

    try:
        r = await http.post(url, content=raw, headers=headers, timeout=5.0)
        status = getattr(r, "status_code", None)
        ok = status is not None and 200 <= int(status) < 300
        summary["webhook"] = {
            "dispatched": True,
            "status_code": status,
            "ok": ok,
        }
        jstatus = "acked" if ok else "non_2xx"
        append_enforcement_journal(
            {
                **base_journal,
                "status": jstatus,
                "http_status": status,
            }
        )
        summary["journal"] = {"status": jstatus}
        if not ok:
            log.warning(
                "enforcement_webhook_non_2xx status=%s action=%s trace_id=%s",
                status,
                intent.action,
                trace_id,
            )
    except Exception as e:
        log.warning(
            "enforcement_webhook_failed action=%s trace_id=%s: %s",
            intent.action,
            trace_id,
            e,
        )
        summary["webhook"] = {
            "dispatched": True,
            "ok": False,
            "error": str(e)[:200],
        }
        append_enforcement_journal(
            {
                **base_journal,
                "status": "error",
                "error": str(e)[:200],
            }
        )
        summary["journal"] = {"status": "error"}
    return summary
