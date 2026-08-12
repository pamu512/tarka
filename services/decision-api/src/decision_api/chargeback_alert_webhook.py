"""Normalize Ethoca/Verifi-class early-alert webhooks → evaluate features + dispute hints."""

from __future__ import annotations

from typing import Any


def _truthy(val: Any) -> bool | None:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("1", "true", "yes", "y"):
            return True
        if s in ("0", "false", "no", "n"):
            return False
    return None


def _evidence_pack_from_payload(pl: dict[str, Any]) -> dict[str, Any]:
    """Host/Downstream evidence fields for representment (no LIVE card network)."""
    ev = pl.get("evidence") if isinstance(pl.get("evidence"), dict) else {}
    srcs = (ev, pl)
    pack: dict[str, Any] = {}

    def _pick_bool(*keys: str) -> bool | None:
        for src in srcs:
            for k in keys:
                if k in src:
                    t = _truthy(src[k])
                    if t is not None:
                        return t
        return None

    for out_key, keys in (
        ("has_pod", ("has_pod", "pod", "proof_of_delivery")),
        ("has_tracking", ("has_tracking", "tracking")),
        ("has_chat", ("has_chat", "chat_log")),
        ("has_id_check", ("has_id_check", "id_verified")),
        ("has_avs", ("has_avs", "avs_match", "avs")),
        ("has_3ds", ("has_3ds", "three_ds", "3ds")),
    ):
        v = _pick_bool(*keys)
        if v is not None:
            pack[out_key] = v

    pdfs: list[str] = []
    for src in srcs:
        raw = src.get("evidence_pdf_urls") or src.get("evidence_pdfs") or src.get("pdf_urls")
        if isinstance(raw, list):
            for u in raw[:16]:
                s = str(u or "").strip()
                if s:
                    pdfs.append(s[:512])
        single = src.get("evidence_pdf_url") or src.get("pdf_url")
        if isinstance(single, str) and single.strip():
            pdfs.append(single.strip()[:512])
    if pdfs:
        pack["evidence_pdf_urls"] = list(dict.fromkeys(pdfs))
    return pack


def build_evaluate_reprocess_metadata(
    *,
    dispute_hint: dict[str, Any],
    features: dict[str, Any],
) -> dict[str, Any]:
    """Metadata block hosts can POST back into evaluate after alert → dispute."""
    evidence = {
        k: dispute_hint[k]
        for k in (
            "has_pod",
            "has_tracking",
            "has_chat",
            "has_id_check",
            "has_avs",
            "has_3ds",
            "evidence_pdf_urls",
        )
        if k in dispute_hint
    }
    if dispute_hint.get("reason_code"):
        evidence["reason_code"] = dispute_hint["reason_code"]
    hint_public = {
        k: v
        for k, v in dispute_hint.items()
        if k != "evaluate_reprocess"
    }
    return {
        "checkpoint": "chargeback",
        "chargeback_early_alert": True,
        "dispute_id": dispute_hint.get("dispute_id"),
        "dispute_hint": hint_public,
        "dispute_evidence": evidence,
        "chargeback_alert_id": features.get("chargeback_alert_id"),
        "chargeback_reason_code": features.get("chargeback_reason_code"),
    }


def normalize_chargeback_alert_payload(
    provider: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map consortium webhook shapes to Tarka marketplace features.

    Does not call card networks — host/vendor gateway posts here after consortium delivery.
    """
    pl = payload if isinstance(payload, dict) else {}
    prov = (provider or "generic").strip().lower() or "generic"

    txn = (
        pl.get("transaction_id")
        or pl.get("txn_id")
        or pl.get("arn")
        or pl.get("acquirer_reference_number")
        or pl.get("order_id")
    )
    alert_id = pl.get("alert_id") or pl.get("id") or pl.get("ethoca_id") or pl.get("case_id")
    severity = str(pl.get("severity") or pl.get("risk_level") or pl.get("priority") or "").lower()
    amount = pl.get("amount") or pl.get("transaction_amount")
    currency = pl.get("currency") or pl.get("transaction_currency")
    reason = pl.get("reason_code") or pl.get("chargeback_reason_code") or pl.get("code")

    # Explicit no-alert / resolution
    resolved = str(pl.get("status") or "").lower() in (
        "resolved",
        "cancelled",
        "closed",
        "false_positive",
    )
    has_alert = not resolved and bool(
        pl.get("alert")
        or pl.get("has_alert")
        or pl.get("matched")
        or alert_id
        or prov in ("ethoca", "verifi", "rdr")
        and txn
    )

    features: dict[str, Any] = {
        "chargeback_early_alert": has_alert,
        "chargeback_alert_provider": prov,
    }
    if txn is not None:
        features["transaction_id"] = str(txn)[:256]
    if alert_id is not None:
        features["chargeback_alert_id"] = str(alert_id)[:256]
    if severity:
        features["chargeback_alert_severity"] = severity[:64]
    if amount is not None:
        try:
            features["amount"] = float(amount)
        except (TypeError, ValueError):
            pass
    if isinstance(currency, str) and currency.strip():
        features["currency"] = currency.strip().upper()[:8]
    if reason is not None:
        features["chargeback_reason_code"] = str(reason)[:64]

    tags = ["vertical:marketplace", "risk:friendly_fraud"]
    host_actions: list[str] = []
    if has_alert:
        tags.append("action:dispute_open")
        host_actions.append("dispute_open")
        if severity in ("high", "critical", "urgent"):
            tags.append("action:refund_hold")
            host_actions.append("refund_hold")

    dispute_hint: dict[str, Any] | None = None
    if has_alert:
        dispute_hint = {
            "dispute_type": "chargeback",
            "source": f"consortium:{prov}",
            "alert_id": features.get("chargeback_alert_id"),
            "transaction_id": features.get("transaction_id"),
            "reason_code": features.get("chargeback_reason_code"),
            "live_claim_allowed": False,
            **_evidence_pack_from_payload(pl),
        }
        dispute_hint["evaluate_reprocess"] = build_evaluate_reprocess_metadata(
            dispute_hint=dispute_hint, features=features
        )

    return {
        "schema_id": "tarka.chargeback_alert_webhook/v1",
        "provider": prov,
        "features": features,
        "tags": tags if has_alert else ["vertical:marketplace"],
        "host_actions": host_actions,
        "dispute_hint": dispute_hint,
        "note": "Feed features into evaluate / open dispute via case-api — connector, not DIY network.",
    }
