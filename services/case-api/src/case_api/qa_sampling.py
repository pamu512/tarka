"""QA sampling for closed cases — second-review queue (maturity Wave 3)."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime
from typing import Any, Sequence


def sample_case_ids(
    case_ids: Sequence[str],
    *,
    rate: float = 0.1,
    seed: str | None = None,
    limit: int = 50,
) -> list[str]:
    """Deterministic sample of closed-case IDs for QA (stable for a given seed)."""
    if not case_ids:
        return []
    rate = max(0.0, min(1.0, float(rate)))
    if rate <= 0:
        return []
    material = sorted({str(c).strip() for c in case_ids if str(c).strip()})
    salt = (seed or datetime.now(UTC).strftime("%Y-%m-%d")).encode("utf-8")
    scored: list[tuple[float, str]] = []
    for cid in material:
        h = hashlib.sha256(salt + cid.encode("utf-8")).hexdigest()
        scored.append((int(h[:8], 16) / 0xFFFFFFFF, cid))
    scored.sort(key=lambda x: x[0])
    n = max(1, min(int(limit), int(round(len(scored) * rate))))
    return [cid for _, cid in scored[:n]]


def disagreement_metrics(
    reviews: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Compute agreement rate between original disposition and QA review."""
    total = 0
    disagree = 0
    for row in reviews:
        orig = str(row.get("original_status") or "").strip().upper()
        qa = str(row.get("qa_status") or "").strip().upper()
        if not orig or not qa:
            continue
        total += 1
        if orig != qa:
            disagree += 1
    agree = total - disagree
    return {
        "reviewed": total,
        "agree": agree,
        "disagree": disagree,
        "agreement_rate": round(agree / total, 4) if total else None,
        "disagreement_rate": round(disagree / total, 4) if total else None,
    }


def random_seed_token() -> str:
    return f"qa-{random.randint(1, 1_000_000_000)}"
