"""FinCEN BSA E-Filing transport: XML handoff + SFTP/ACK state machine (integration stubs)."""

from __future__ import annotations

import enum
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


class SarFilingState(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    ACK_PENDING = "ack_pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMENDMENT_REQUIRED = "amendment_required"


@dataclass
class SarSubmissionEnvelope:
    """WORM-friendly audit payload (store blob in object storage in production)."""

    filing_id: str
    xml_payload: str
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fincen_batch_id: str | None = None
    ack_raw: str | None = None
    state: SarFilingState = SarFilingState.SUBMITTED


def build_sftp_destination() -> str | None:
    return os.environ.get("FINCEN_BSA_SFTP_HOST", "").strip() or None


def schedule_ack_poll(envelope: SarSubmissionEnvelope) -> None:
    """Async worker hook: poll FinCEN SFTP for ACK/NAK and transition ``SarFiling`` rows."""
    if not build_sftp_destination():
        log.info("FINCEN_BSA_SFTP_HOST unset — ACK poll not scheduled for %s", envelope.filing_id)
        return
    log.info(
        "sar_ack_poll_scheduled filing=%s state=%s (implement worker + credential vault)",
        envelope.filing_id,
        envelope.state,
    )


def validate_pre_filing(xml_payload: str, required_fields: list[str]) -> list[str]:
    """Return list of blocking validation errors (empty == OK)."""
    errors: list[str] = []
    low = xml_payload.lower()
    for f in required_fields:
        token = f"<{f}"
        if f not in low and token not in low:
            errors.append(f"missing_field:{f}")
    return errors
