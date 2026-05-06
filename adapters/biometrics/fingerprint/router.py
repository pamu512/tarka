"""FastAPI router for Fingerprint identification webhooks.

Verifies ``FPJS-Event-Signature`` (``v1`` = HMAC-SHA256 hex over raw body) per Fingerprint docs.

Environment:

- ``FINGERPRINT_WEBHOOK_SIGNING_SECRET`` — symmetric signing key from the dashboard (comma-separated
  for rotation). Required unless ``FINGERPRINT_WEBHOOK_ALLOW_UNSIGNED=1`` (debug only).
- ``FINGERPRINT_REGION`` / ``FINGERPRINT_API_BASE_URL`` — echoed into ``TarkaRiskSignal.provenance``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from .client import _DEFAULT_BASE, RegionName
from .exceptions import FingerprintMalformedPayloadError
from .schemas import TarkaRiskSignal, webhook_payload_to_tarka


def _region_base_url() -> str:
    base = os.environ.get("FINGERPRINT_API_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    region_raw = os.environ.get("FINGERPRINT_REGION", "global").strip().lower()
    region: RegionName = "global"
    if region_raw in ("eu", "europe"):
        region = "eu"
    elif region_raw in ("ap", "asia", "mumbai"):
        region = "ap"
    return _DEFAULT_BASE[region]


def _webhook_secrets() -> list[str]:
    raw = os.environ.get("FINGERPRINT_WEBHOOK_SIGNING_SECRET", "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def verify_fingerprint_webhook_signature(
    raw_body: bytes,
    signature_header: str | None,
    secrets: list[str],
) -> bool:
    """Return True if any configured secret validates a ``v1`` entry in the header."""

    if not signature_header or not secrets:
        return False
    for part in signature_header.split(","):
        chunk = part.strip()
        if "=" not in chunk:
            continue
        ver, digest = chunk.split("=", 1)
        if ver.strip() != "v1":
            continue
        digest = digest.strip()
        for secret in secrets:
            expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, digest):
                return True
    return False


class WebhookAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    signal: TarkaRiskSignal


def build_fingerprint_webhook_router(*, prefix: str = "") -> APIRouter:
    """Return a router with POST ``/webhooks/fingerprint`` (plus optional prefix)."""

    r = APIRouter(prefix=prefix, tags=["integrations", "fingerprint"])

    @r.post(
        "/webhooks/fingerprint",
        response_model=WebhookAcceptedResponse,
        summary="Ingest Fingerprint identification webhook",
    )
    async def fingerprint_webhook(
        request: Request,
        fpjs_event_signature: str | None = Header(default=None, alias="FPJS-Event-Signature"),
    ) -> WebhookAcceptedResponse:
        raw = await request.body()
        if len(raw) > 1_048_576:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="payload exceeds 1 MiB guard",
            )

        allow_unsigned = os.environ.get("FINGERPRINT_WEBHOOK_ALLOW_UNSIGNED", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        secrets = _webhook_secrets()
        if not allow_unsigned:
            if not secrets:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="FINGERPRINT_WEBHOOK_SIGNING_SECRET is not configured",
                )
            if not fpjs_event_signature:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="FPJS-Event-Signature header is required",
                )
            if not verify_fingerprint_webhook_signature(raw, fpjs_event_signature, secrets):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="webhook signature verification failed",
                )
        elif fpjs_event_signature and secrets:
            if not verify_fingerprint_webhook_signature(raw, fpjs_event_signature, secrets):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="webhook signature verification failed",
                )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid JSON: {e}",
            ) from e
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="webhook JSON root must be an object",
            )

        try:
            signal = webhook_payload_to_tarka(payload, region_base_url=_region_base_url())
        except FingerprintMalformedPayloadError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"webhook normalization failed: {e}",
            ) from e

        return WebhookAcceptedResponse(signal=signal)

    return r


fingerprint_webhook_router = build_fingerprint_webhook_router()
