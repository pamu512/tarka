"""Platform enforcement adapters — block / step_up / allow (Wave D).

Invoked from ``DecisionOutcomeHandler``. Does not create investigation cases;
case-api remains a separate outcome path.
"""

from __future__ import annotations

import asyncio
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
DELIVERY_QUERY_SCHEMA = "tarka.enforcement_delivery_query/v1"

# ponytail: in-process N=3 only. Crash loses in-flight retries (journal already has
# retrying / dead_lettered). Durable bus (Redis/SQS/Celery) is out of scope.
ENFORCEMENT_RETRY_ATTEMPTS = 3
ENFORCEMENT_RETRY_BACKOFF_S = (0.05, 0.15)

EnforcementAction = Literal["allow", "step_up", "block"]

ENFORCEMENT_SCHEMA = "tarka.enforcement/v1"
ACTION_ID_SCHEME = "tarka.action_id/v1"

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


def enforcement_mode() -> str:
    env = os.environ.get("TARKA_ENFORCEMENT_MODE", "").strip().lower()
    if env in {"emit_only", "handoff"}:
        return env
    try:
        from desk_provision import enforcement_mode as desk_mode

        return desk_mode()
    except Exception:
        return "emit_only"


def idempotent_action_id(
    *,
    tenant_id: str,
    trace_id: str,
    action: str,
    pack_hash: str = "",
) -> str:
    """Stable hex SHA-256 of tenant + trace_id + action token + pack hash.

    Same tuple → same id across retries. Not a random UUID per POST.
    """
    material = "\n".join(
        (
            ACTION_ID_SCHEME,
            (tenant_id or "").strip(),
            (trace_id or "").strip(),
            (action or "").strip().lower(),
            (pack_hash or "").strip(),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def action_ids_for(
    tokens: list[str],
    *,
    tenant_id: str,
    trace_id: str,
    pack_hash: str = "",
) -> dict[str, str]:
    """Map each suggested_actions token to its idempotent action_id."""
    return {
        token: idempotent_action_id(
            tenant_id=tenant_id,
            trace_id=trace_id,
            action=token,
            pack_hash=pack_hash,
        )
        for token in tokens
    }


def _delivery_action_id(
    tokens: list[str],
    ids: dict[str, str],
    *,
    tenant_id: str,
    trace_id: str,
    pack_hash: str,
) -> str:
    if tokens:
        return ids[tokens[0]]
    return idempotent_action_id(
        tenant_id=tenant_id,
        trace_id=trace_id,
        action="",
        pack_hash=pack_hash,
    )


def suggested_actions(
    decision: str, recommended_action: str | None = None
) -> list[str]:
    """Always-on advisory list for buyer systems. Empty list is valid."""
    d = (decision or "").strip().lower()
    rec = (recommended_action or "").strip().lower()
    out: list[str] = []
    if d in {"deny", "block"}:
        out.append("deny")
    if d in {"review", "flag"}:
        out.append("review" if d == "review" else "flag")
    if "payout" in rec or "hold" in rec:
        out.append("hold_payout")
    if "promo" in rec:
        out.append("deny_promo")
    if "courier" in rec:
        out.append("suspend_courier")
    if is_step_up_recommended(recommended_action):
        out.append("step_up")
    return out


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


def _hook_url() -> str:
    try:
        from desk_provision import hook_url
    except ImportError:
        return os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_URL", "").strip()
    return hook_url("enforcement")


def _hook_secret() -> str:
    try:
        from desk_provision import hook_secret
    except ImportError:
        return os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_SECRET", "").strip()
    return hook_secret("enforcement")


def enforcement_webhook_configured() -> bool:
    return bool(_hook_url())


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
    """Append-only delivery journal (acked / retrying / dead_lettered / skipped). Fail soft."""
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


def logical_enforcement_delivery(action_id: str) -> dict[str, Any] | None:
    """Dedupe journal rows for one G4.2 action_id into a single logical delivery.

    D9.3 GET /v1/enforcement/deliveries reuses this aggregator. Does not skip or
    silent-block POSTs — retries still fire; buyer sinks apply once on this key.
    """
    key = (action_id or "").strip().lower()
    if not key:
        return None
    # ponytail: O(n) jsonl scan. Indexed store is the upgrade path.
    path = enforcement_journal_path()
    if not path.is_file():
        return None
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for ln in fh:
                line = ln.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                aid = str(row.get("action_id") or "").strip().lower()
                ikey = str(row.get("idempotency_key") or "").strip().lower()
                if aid == key or ikey == key:
                    rows.append(row)
    except OSError:
        return None
    if not rows:
        return None
    attempts = 1
    for row in rows:
        raw = row.get("attempt_count")
        try:
            n = int(raw) if raw is not None else 1
        except (TypeError, ValueError):
            n = 1
        if n > attempts:
            attempts = n
    last = rows[-1]
    err = last.get("last_error") or last.get("error")
    return {
        "action_id": key,
        "idempotency_key": key,
        "attempt_count": attempts,
        "status": last.get("status"),
        "trace_id": last.get("trace_id"),
        "tenant_id": last.get("tenant_id"),
        "last_error": err,
        "ts": last.get("ts"),
        "reason": last.get("reason"),
    }


def map_journal_query_status(status: str | None, reason: str | None = None) -> str:
    """Map journal status → query last_status. Journal HTTP 2xx is not product ACK."""
    raw = str(status or "").strip().lower()
    why = str(reason or "").strip().lower()
    if raw == "skipped" or why == "webhook_unset":
        return "not_configured"
    if raw in {"retrying", "dead_lettered"}:
        return raw
    if raw == "acked":
        return "emitted"
    return raw or "emitted"


def _action_ids_for_query(
    trace_id: str, tenant_id: str, action_id: str | None
) -> list[str]:
    tid = (trace_id or "").strip()
    ten = (tenant_id or "").strip()
    wanted = (action_id or "").strip().lower()
    if not tid or not ten:
        return []
    path = enforcement_journal_path()
    if not path.is_file():
        return []
    seen: list[str] = []
    found: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for ln in fh:
                line = ln.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if str(row.get("trace_id") or "") != tid:
                    continue
                if str(row.get("tenant_id") or "") != ten:
                    continue
                aid = str(
                    row.get("action_id") or row.get("idempotency_key") or ""
                ).strip().lower()
                if not aid or (wanted and aid != wanted) or aid in found:
                    continue
                found.add(aid)
                seen.append(aid)
    except OSError:
        return []
    return seen


def _logical_to_query_row(logical: dict[str, Any]) -> dict[str, Any]:
    raw = str(logical.get("status") or "").strip().lower()
    reason = str(logical.get("reason") or "").strip().lower()
    err = logical.get("last_error")
    acked_at = None
    if raw == "acked":
        ts = str(logical.get("ts") or "").strip()
        acked_at = ts or None
    return {
        "trace_id": logical.get("trace_id"),
        "tenant_id": logical.get("tenant_id"),
        "action_id": logical.get("action_id"),
        "attempt_count": int(logical.get("attempt_count") or 1),
        "last_status": map_journal_query_status(raw, reason),
        "last_error": str(err).strip() if err else None,
        "acked_at": acked_at,
    }


def query_enforcement_deliveries(
    *,
    trace_id: str,
    tenant_id: str,
    action_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Tenant-scoped logical deliveries. Unknown trace → []. Reuses logical_enforcement_delivery."""
    tid = (trace_id or "").strip()
    ten = (tenant_id or "").strip()
    want_status = (status or "").strip().lower()
    if not tid or not ten:
        return []
    out: list[dict[str, Any]] = []
    for aid in _action_ids_for_query(tid, ten, action_id):
        logical = logical_enforcement_delivery(aid)
        if logical is None:
            continue
        if str(logical.get("tenant_id") or "") != ten:
            continue
        if str(logical.get("trace_id") or "") != tid:
            continue
        row = _logical_to_query_row(logical)
        if want_status and row["last_status"] != want_status:
            continue
        out.append(row)
    return out


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _retry_wait(attempt: int) -> None:
    """Backoff after a failed attempt. Tests monkeypatch this to 0."""
    if 1 <= attempt <= len(ENFORCEMENT_RETRY_BACKOFF_S):
        await asyncio.sleep(ENFORCEMENT_RETRY_BACKOFF_S[attempt - 1])


def _retryable(*, status: int | None, error: str | None) -> bool:
    if error:
        return True
    if status is None:
        return True
    code = int(status)
    return code >= 500 or code == 429


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
    pack_hash: str = "",
) -> dict[str, Any]:
    hints = suggested_actions(intent.decision, intent.recommended_action)
    ids = action_ids_for(
        hints, tenant_id=tenant_id, trace_id=trace_id, pack_hash=pack_hash
    )
    delivery_id = _delivery_action_id(
        hints, ids, tenant_id=tenant_id, trace_id=trace_id, pack_hash=pack_hash
    )
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
        "suggested_actions": hints,
        "action_id": delivery_id,
        "idempotency_key": delivery_id,
        "action_ids": ids,
        "enforcement_mode": enforcement_mode(),
        "authority": enforcement_mode() == "handoff",
        "webhook_event": (
            "decision.enforced"
            if enforcement_mode() == "handoff"
            else "decision.emitted"
        ),
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
    pack_hash: str = "",
    metrics_inc: MetricsInc | None = None,
) -> dict[str, Any]:
    """Emit enforcement metrics and optional tenant webhook for allow/step_up/block.

    Fail soft: webhook/metric errors are logged and retried in-process (N=3);
    never raises into evaluate and never converts a delivery miss into block/deny.
    """
    intent = resolve_enforcement_intent(decision, recommended_action)
    mode = enforcement_mode()
    hints = suggested_actions(decision, recommended_action)
    ids = action_ids_for(
        hints, tenant_id=tenant_id, trace_id=trace_id, pack_hash=pack_hash
    )
    delivery_id = _delivery_action_id(
        hints, ids, tenant_id=tenant_id, trace_id=trace_id, pack_hash=pack_hash
    )
    summary: dict[str, Any] = {
        "enforcement_action": intent.action,
        "enforcement_mode": mode,
        "authority": mode == "handoff",
        "suggested_actions": hints,
        "action_id": delivery_id,
        "idempotency_key": delivery_id,
        "action_ids": ids,
        "webhook": None,
        "webhook_event": "decision.enforced"
        if mode == "handoff"
        else "decision.emitted",
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

    url = _hook_url()
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
        "enforcement_mode": mode,
        "webhook_event": summary["webhook_event"],
        "action_id": delivery_id,
        "idempotency_key": delivery_id,
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
        pack_hash=pack_hash,
    )
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "x-tarka-enforcement-event": intent.action,
    }
    secret = _hook_secret()
    if secret:
        headers["x-tarka-signature"] = _sign(raw, secret)

    last_status: int | None = None
    last_error: str | None = None
    for attempt in range(1, ENFORCEMENT_RETRY_ATTEMPTS + 1):
        ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        attempt_journal: dict[str, Any] = {
            **base_journal,
            "ts": ts,
            "attempt_count": attempt,
        }
        ok = False
        last_status = None
        last_error = None
        try:
            r = await http.post(url, content=raw, headers=headers, timeout=5.0)
            last_status = getattr(r, "status_code", None)
            ok = last_status is not None and 200 <= int(last_status) < 300
        except Exception as e:
            last_error = str(e)[:200]
            log.warning(
                "enforcement_webhook_failed action=%s trace_id=%s attempt=%s: %s",
                intent.action,
                trace_id,
                attempt,
                e,
            )

        if ok:
            summary["webhook"] = {
                "dispatched": True,
                "status_code": last_status,
                "ok": True,
            }
            append_enforcement_journal(
                {**attempt_journal, "status": "acked", "http_status": last_status}
            )
            summary["journal"] = {"status": "acked"}
            return summary

        will_retry = attempt < ENFORCEMENT_RETRY_ATTEMPTS and _retryable(
            status=last_status, error=last_error
        )
        if will_retry:
            row: dict[str, Any] = {**attempt_journal, "status": "retrying"}
            if last_error:
                row["error"] = last_error
            else:
                row["http_status"] = last_status
                log.warning(
                    "enforcement_webhook_non_2xx status=%s action=%s trace_id=%s attempt=%s",
                    last_status,
                    intent.action,
                    trace_id,
                    attempt,
                )
            append_enforcement_journal(row)
            await _retry_wait(attempt)
            continue

        summary["webhook"] = {
            "dispatched": True,
            "ok": False,
        }
        if last_status is not None:
            summary["webhook"]["status_code"] = last_status
        if last_error:
            summary["webhook"]["error"] = last_error
        if _retryable(status=last_status, error=last_error):
            last_err = last_error or f"http_{last_status}"
            append_enforcement_journal(
                {
                    **attempt_journal,
                    "status": "dead_lettered",
                    "last_error": last_err,
                    "http_status": last_status,
                }
            )
            summary["journal"] = {"status": "dead_lettered"}
        elif last_error:
            append_enforcement_journal(
                {**attempt_journal, "status": "error", "error": last_error}
            )
            summary["journal"] = {"status": "error"}
        else:
            append_enforcement_journal(
                {**attempt_journal, "status": "non_2xx", "http_status": last_status}
            )
            summary["journal"] = {"status": "non_2xx"}
            log.warning(
                "enforcement_webhook_non_2xx status=%s action=%s trace_id=%s",
                last_status,
                intent.action,
                trace_id,
            )
        return summary
    return summary
