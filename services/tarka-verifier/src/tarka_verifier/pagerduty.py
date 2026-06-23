"""PagerDuty Events API v2 — alert on verification failures (bounded retries)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyDeliveryError(Exception):
    """PagerDuty rejected the event or HTTP transport failed after retries."""


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=0.3, max=8.0),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    reraise=True,
)
def _post_event(payload: dict[str, Any], *, timeout_seconds: float) -> httpx.Response:
    with httpx.Client(timeout=timeout_seconds) as client:
        return client.post(PAGERDUTY_EVENTS_URL, json=payload)


def trigger_incident(
    *,
    routing_key: str,
    summary: str,
    source: str,
    severity: str,
    custom_details: dict[str, Any],
    dedup_key: str | None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Send ``event_action=trigger`` to PagerDuty Events API v2."""
    body: dict[str, Any] = {
        "routing_key": routing_key.strip(),
        "event_action": "trigger",
        "payload": {
            "summary": summary[:1024],
            "source": source[:255],
            "severity": severity,
            "custom_details": custom_details,
        },
    }
    if dedup_key:
        body["dedup_key"] = dedup_key[:255]

    try:
        resp = _post_event(body, timeout_seconds=timeout_seconds)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise PagerDutyDeliveryError(f"pagerduty transport failure: {exc}") from exc

    if resp.status_code >= 400:
        raise PagerDutyDeliveryError(
            f"pagerduty http {resp.status_code}: {resp.text[:2048]}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise PagerDutyDeliveryError("pagerduty response not json") from exc

    if data.get("status") != "success":
        raise PagerDutyDeliveryError(f"pagerduty logical failure: {data!r}")

    log.warning(
        "pagerduty incident triggered summary=%s dedup=%s",
        summary[:120],
        dedup_key,
    )
    return data


def alert_verification_failure(
    *,
    routing_key: str,
    failure_codes: tuple[str, ...],
    merkle_root_hex: str | None,
    details: dict[str, Any],
    manifest_digest_hex: str,
    timeout_seconds: float = 12.0,
) -> None:
    """Raise operational visibility when cryptographic verification fails."""
    trigger_incident(
        routing_key=routing_key,
        summary=(
            "Tarka verifier: EvidenceManifest verification FAILED "
            f"({', '.join(failure_codes) or 'unknown'})"
        ),
        source="tarka-verifier",
        severity="critical",
        custom_details={
            "failure_codes": list(failure_codes),
            "merkle_root_hex": merkle_root_hex,
            "manifest_sha256": manifest_digest_hex,
            "details": details,
        },
        dedup_key=f"tarka-verify|{manifest_digest_hex}|{','.join(sorted(failure_codes))}",
        timeout_seconds=timeout_seconds,
    )
