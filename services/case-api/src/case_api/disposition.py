"""Disposition reason codes + maker-checker for high-impact case closes (bridge B2/C1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Stable enum → calibration ground-truth class (FRAUD / LEGITIMATE).
DISPOSITION_REASON_CODES: dict[str, str] = {
    "CONFIRMED_FRAUD": "FRAUD",
    "ACCOUNT_TAKEOVER": "FRAUD",
    "FRIENDLY_FRAUD": "FRAUD",
    "SAR_FILED": "FRAUD",
    "FALSE_POSITIVE": "LEGITIMATE",
    "CUSTOMER_CLEARED": "LEGITIMATE",
    "INSUFFICIENT_EVIDENCE": "LEGITIMATE",
}

_TERMINAL = frozenset({"resolved", "closed", "resolved_fraud", "resolved_legit", "sar_filed"})
_DEFAULT_MC_STATUSES = frozenset({"resolved_fraud", "sar_filed"})
_MC_PENDING_PREFIX = "mc_pending:"
_MC_REQUESTER_PREFIX = "mc_requester:"
_REASON_LABEL_PREFIX = "disposition:"


def parse_maker_checker_statuses(raw: str | None) -> frozenset[str]:
    token = (raw or "").strip()
    if not token:
        return _DEFAULT_MC_STATUSES
    out = {p.strip().lower() for p in token.split(",") if p.strip()}
    return frozenset(out) if out else _DEFAULT_MC_STATUSES


def normalize_reason_code(raw: str | None) -> str:
    token = (raw or "").strip().upper()
    if not token:
        return ""
    if token not in DISPOSITION_REASON_CODES:
        raise ValueError(f"unknown disposition_reason_code: {token}")
    return token


def y_label_class_for_reason(reason_code: str) -> str:
    return DISPOSITION_REASON_CODES[normalize_reason_code(reason_code)]


def is_terminal_status(status: str | None) -> bool:
    return (status or "").strip().lower() in _TERMINAL


def escalate_status_for_reason(status: str, reason_code: str | None) -> str:
    """Map plain resolved/closed + fraud reason → high-impact status for maker-checker."""
    st = (status or "").strip().lower()
    if not reason_code:
        return st
    reason = normalize_reason_code(reason_code)
    y = DISPOSITION_REASON_CODES[reason]
    if st in {"resolved", "closed"} and y == "FRAUD":
        return "sar_filed" if reason == "SAR_FILED" else "resolved_fraud"
    if st in {"resolved", "closed"} and y == "LEGITIMATE":
        return "resolved_legit" if st == "resolved" else st
    return st


def _strip_mc_labels(labels: list[str]) -> list[str]:
    return [
        x
        for x in labels
        if not str(x).startswith(_MC_PENDING_PREFIX) and not str(x).startswith(_MC_REQUESTER_PREFIX)
    ]


def pending_target_status(labels: list[str] | None) -> str | None:
    for item in labels or []:
        s = str(item)
        if s.startswith(_MC_PENDING_PREFIX):
            return s[len(_MC_PENDING_PREFIX) :].strip().lower() or None
    return None


def pending_requester(labels: list[str] | None) -> str | None:
    for item in labels or []:
        s = str(item)
        if s.startswith(_MC_REQUESTER_PREFIX):
            return s[len(_MC_REQUESTER_PREFIX) :].strip() or None
    return None


@dataclass
class MakerCheckerResult:
    status_applied: bool
    pending: bool
    target_status: str | None
    requester: str | None
    labels: list[str]
    status: str
    detail: str


def apply_status_with_maker_checker(
    *,
    current_status: str,
    current_labels: list[str] | None,
    actor: str,
    requested_status: str | None,
    reason_code: str | None,
    approve: bool,
    maker_statuses: frozenset[str],
) -> MakerCheckerResult:
    """Mutate-free: returns new status/labels. Raises ValueError on policy violations."""
    labels = list(current_labels or [])
    actor_id = (actor or "").strip() or "anonymous"
    if approve:
        target = pending_target_status(labels)
        requester = pending_requester(labels)
        if not target:
            raise ValueError("no pending maker-checker disposition to approve")
        if requester and requester == actor_id:
            raise ValueError("maker-checker requires a distinct second actor")
        clean = _strip_mc_labels(labels)
        if reason_code:
            code = normalize_reason_code(reason_code)
            clean = [x for x in clean if not str(x).startswith(_REASON_LABEL_PREFIX)]
            clean.append(f"{_REASON_LABEL_PREFIX}{code}")
        return MakerCheckerResult(
            status_applied=True,
            pending=False,
            target_status=target,
            requester=requester,
            labels=sorted(set(clean)),
            status=target,
            detail="approved",
        )

    if requested_status is None:
        return MakerCheckerResult(
            status_applied=False,
            pending=bool(pending_target_status(labels)),
            target_status=pending_target_status(labels),
            requester=pending_requester(labels),
            labels=labels,
            status=current_status,
            detail="no_status_change",
        )

    target = escalate_status_for_reason(requested_status, reason_code)
    if reason_code:
        normalize_reason_code(reason_code)

    if target in maker_statuses:
        clean = _strip_mc_labels(labels)
        if reason_code:
            code = normalize_reason_code(reason_code)
            clean = [x for x in clean if not str(x).startswith(_REASON_LABEL_PREFIX)]
            clean.append(f"{_REASON_LABEL_PREFIX}{code}")
        clean.append(f"{_MC_PENDING_PREFIX}{target}")
        clean.append(f"{_MC_REQUESTER_PREFIX}{actor_id}")
        return MakerCheckerResult(
            status_applied=False,
            pending=True,
            target_status=target,
            requester=actor_id,
            labels=sorted(set(clean)),
            status=current_status,
            detail="pending_second_actor",
        )

    clean = _strip_mc_labels(labels)
    if reason_code:
        code = normalize_reason_code(reason_code)
        clean = [x for x in clean if not str(x).startswith(_REASON_LABEL_PREFIX)]
        clean.append(f"{_REASON_LABEL_PREFIX}{code}")
    return MakerCheckerResult(
        status_applied=True,
        pending=False,
        target_status=target,
        requester=None,
        labels=sorted(set(clean)),
        status=target,
        detail="applied",
    )


def maker_checker_public(labels: list[str] | None, status: str) -> dict[str, Any]:
    return {
        "pending": bool(pending_target_status(labels)),
        "target_status": pending_target_status(labels),
        "requester": pending_requester(labels),
        "status": status,
    }
