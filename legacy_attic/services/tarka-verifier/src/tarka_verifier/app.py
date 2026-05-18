"""HTTP API for independent EvidenceManifest verification."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from typing import Any

import anyio
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from tarka_verifier.pagerduty import PagerDutyDeliveryError, alert_verification_failure
from tarka_verifier.settings import VerifierSettings, get_settings
from tarka_verifier.verify_pipeline import VerificationReport, decode_hex_pubkey, verify_evidence_bundle

log = logging.getLogger(__name__)


class VerifyRequest(BaseModel):
    manifest_protobuf_base64: str = Field(..., description="Raw EvidenceManifest protobuf, base64-encoded.")
    merkle_proof_bytes_base64: str = Field(
        ...,
        description="rs_merkle ``MerkleProof::to_bytes()`` (DirectHashesOrder), base64-encoded.",
    )
    signature_bytes_base64: str | None = Field(
        default=None,
        description="Optional detached signature override (64 bytes). Default: ``manifest.signature`` (wire).",
    )


def create_app() -> FastAPI:
    application = FastAPI(
        title="Tarka Verifier",
        version="0.1.0",
        description="Independent auditor: trace Merkle + Ed25519ph (KMS-compatible).",
    )

    @application.post("/v1/verify")
    async def verify_endpoint(
        body: VerifyRequest,
        settings: VerifierSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        pk_hex = (settings.verifying_key_hex or "").strip()
        if not pk_hex:
            raise HTTPException(
                status_code=503,
                detail={
                    "reason_code": "VERIFIER_MISCONFIGURED",
                    "message": "TARKA_VERIFIER_VERIFYING_KEY_HEX is not set.",
                },
            )

        try:
            verifying_key = decode_hex_pubkey(pk_hex)
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "reason_code": "VERIFIER_KEY_INVALID",
                    "message": str(exc),
                },
            ) from exc

        try:
            manifest_raw = base64.b64decode(body.manifest_protobuf_base64, validate=True)
            proof_raw = base64.b64decode(body.merkle_proof_bytes_base64, validate=True)
        except binascii.Error as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason_code": "BASE64_DECODE_ERROR",
                    "message": str(exc),
                },
            ) from exc

        sig_override: bytes | None = None
        if body.signature_bytes_base64 is not None:
            try:
                sig_override = base64.b64decode(body.signature_bytes_base64, validate=True)
            except binascii.Error as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"reason_code": "SIGNATURE_BASE64_INVALID", "message": str(exc)},
                ) from exc

        def _run_verify() -> VerificationReport:
            return verify_evidence_bundle(
                manifest_protobuf=manifest_raw,
                merkle_proof_bytes=proof_raw,
                verifying_public_key=verifying_key,
                signature_override=sig_override,
            )

        report = await anyio.to_thread.run_sync(_run_verify)

        digest = hashlib.sha256(manifest_raw).hexdigest()
        response: dict[str, Any] = {
            "valid": report.ok,
            "merkle_root_hex": report.merkle_root_hex,
            "failure_codes": list(report.failure_codes),
            "details": report.details,
            "manifest_sha256": digest,
        }

        if not report.ok and (settings.pagerduty_routing_key or "").strip():
            try:
                await anyio.to_thread.run_sync(
                    _pagerduty_alert_sync,
                    settings,
                    report,
                    digest,
                )
            except PagerDutyDeliveryError as exc:
                log.error("pagerduty delivery failed after retries: %s", exc)
                response["pagerduty_error"] = str(exc)

        return response

    return application


def _pagerduty_alert_sync(
    settings: VerifierSettings,
    report: VerificationReport,
    digest: str,
) -> None:
    alert_verification_failure(
        routing_key=settings.pagerduty_routing_key.strip(),
        failure_codes=report.failure_codes,
        merkle_root_hex=report.merkle_root_hex,
        details=report.details,
        manifest_digest_hex=digest,
        timeout_seconds=settings.pagerduty_timeout_seconds,
    )


app = create_app()
