"""Optional job: new labels → Observe drafts. Never auto Active."""

from __future__ import annotations

from typing import Any

from decision_api.l2_draft import L2DraftError, build_l2_draft, find_open_draft


def drafts_from_labels(
    *,
    packs: list[dict[str, Any]],
    labels: dict[str, Any],
    tenant_id: str,
) -> list[dict[str, Any]]:
    kinds = labels.get("label_kind_by_trace") if isinstance(labels, dict) else {}
    kinds = kinds if isinstance(kinds, dict) else {}
    out: list[dict[str, Any]] = []
    for token, kind in kinds.items():
        token = str(token).strip()
        kind = str(kind).strip().lower()
        if not token or kind not in {"fp", "chargeback", "promo_abuse"}:
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
