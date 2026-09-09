"""Optional job: joined labels since T → Observe drafts. Never auto Active."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from decision_api.l2_draft import L2DraftError, build_l2_draft, find_open_draft

CONSUME_OWNER = "buyer"
CONSUME_IS_CRM = False
CONSUME_AUTO_PROMOTE = False
_MINT_KINDS = frozenset({"fp", "chargeback", "promo_abuse"})


def _parse_ts(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def drafts_from_labels(
    *,
    packs: list[dict[str, Any]],
    labels: dict[str, Any],
    tenant_id: str,
    since: str | None = None,
) -> list[dict[str, Any]]:
    kinds = labels.get("label_kind_by_trace") if isinstance(labels, dict) else {}
    kinds = kinds if isinstance(kinds, dict) else {}
    labeled_at = labels.get("labeled_at_by_trace") if isinstance(labels, dict) else {}
    labeled_at = labeled_at if isinstance(labeled_at, dict) else {}
    cutoff = _parse_ts(since)
    out: list[dict[str, Any]] = []
    for token, kind in kinds.items():
        token = str(token).strip()
        kind = str(kind).strip().lower()
        if not token or kind not in _MINT_KINDS:
            continue
        if cutoff is not None:
            stamped = _parse_ts(labeled_at.get(token))
            if stamped is None or stamped < cutoff:
                continue
        hil = f"label:{token}"
        if find_open_draft(packs, leftover_id="", hil_event_id=hil):
            continue
        receipt = {
            "tenant_id": tenant_id,
            "entity_id": token,
            "trace_id": token,
            "user_id": token,
        }
        try:
            pack = build_l2_draft(
                receipt=receipt,
                hil_event_id=hil,
                override_why=f"label_kind={kind}",
                authored_by="seed",
                is_ai_authored=False,
                skip_backtest=True,
                actor="label-job",
                skip_reason="label-driven observe draft",
                intent="soften" if kind == "fp" else "",
            )
        except L2DraftError:
            continue
        pack["mode"] = "shadow"
        out.append(pack)
    return out


def consume_joined_labels(
    *,
    packs: list[dict[str, Any]],
    tenant_id: str,
    training_rows: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
    labels: dict[str, Any] | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Buyer-owned optional consume. Joined labels since T → Observe. Never Active."""
    rows = list(training_rows) if isinstance(training_rows, list) else []
    if not rows and receipts is not None and labels is not None:
        from decision_api.receipt_export import join_training_rows

        rows = join_training_rows(receipts, labels)
    if not rows:
        return []
    src = labels if isinstance(labels, dict) else {}
    src_kinds = src.get("label_kind_by_trace")
    src_kinds = src_kinds if isinstance(src_kinds, dict) else {}
    src_at = src.get("labeled_at_by_trace")
    src_at = src_at if isinstance(src_at, dict) else {}
    kinds: dict[str, Any] = {}
    stamped: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        token = str(row.get("evaluation_token") or "").strip()
        kind = str(row.get("label_kind") or src_kinds.get(token) or "").strip()
        if not token or not kind:
            continue
        kinds[token] = kind
        at = row.get("labeled_at") or src_at.get(token)
        if str(at or "").strip():
            stamped[token] = at
    return drafts_from_labels(
        packs=packs,
        labels={"label_kind_by_trace": kinds, "labeled_at_by_trace": stamped},
        tenant_id=tenant_id,
        since=since,
    )
