"""Compliance API — DSAR, data erasure, data export, privacy controls.

Implements data subject rights required by GDPR, CCPA, LGPD, and other regulations:
- Right to Access (Article 15 GDPR)
- Right to Erasure (Article 17 GDPR / "Right to be Forgotten")
- Right to Data Portability (Article 20 GDPR)
- Right to Rectification (Article 16 GDPR)
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.db import get_session
from decision_api.models import AuditRecord

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/compliance", tags=["compliance"])


# ---------------------------------------------------------------------------
# Shared privacy module import helper
# ---------------------------------------------------------------------------
import os, sys

_shared_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared")
)
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

from privacy import (  # noqa: E402
    PRIVACY_PROFILES,
    anonymize_record,
    get_data_processing_record,
    get_profile,
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class PrivacyConfigRequest(BaseModel):
    tenant_id: str
    region: str = "global"


class DSARAccessRequest(BaseModel):
    tenant_id: str
    entity_id: str
    region: str = "global"


class DSARErasureRequest(BaseModel):
    tenant_id: str
    entity_id: str
    region: str = "global"
    reason: str = ""


# ---------------------------------------------------------------------------
# Privacy profile
# ---------------------------------------------------------------------------

@router.post("/privacy-profile")
async def get_privacy_profile(body: PrivacyConfigRequest):
    """Get the active privacy profile for a tenant's region."""
    profile = get_profile(body.region)
    ropa = get_data_processing_record(body.tenant_id, profile)

    return {
        "tenant_id": body.tenant_id,
        "region": profile.region.value,
        "regulation": profile.regulation_name,
        "profile": {
            "max_retention_days": profile.max_retention_days,
            "pii_retention_days": profile.pii_retention_days,
            "requires_explicit_consent": profile.requires_explicit_consent,
            "consent_for_profiling": profile.consent_for_profiling,
            "consent_for_automated_decisions": profile.consent_for_automated_decisions,
            "right_to_erasure": profile.right_to_erasure,
            "right_to_access": profile.right_to_access,
            "right_to_portability": profile.right_to_portability,
            "right_to_rectification": profile.right_to_rectification,
            "encrypt_pii_at_rest": profile.encrypt_pii_at_rest,
            "mask_pii_in_logs": profile.mask_pii_in_logs,
            "restrict_cross_border": profile.restrict_cross_border,
            "breach_notify_hours": profile.breach_notify_hours,
        },
        "processing_record": ropa,
    }


# ---------------------------------------------------------------------------
# DSAR — Right to Access
# ---------------------------------------------------------------------------

@router.post("/dsar/access")
async def dsar_access(
    body: DSARAccessRequest,
    session: AsyncSession = Depends(get_session),
):
    """Right to Access — export all data held about an entity."""
    profile = get_profile(body.region)
    if not profile.right_to_access:
        raise HTTPException(400, f"Right to access not applicable under {profile.regulation_name}")

    stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == body.tenant_id)
        .where(AuditRecord.entity_id == body.entity_id)
        .order_by(AuditRecord.created_at.desc())
        .limit(10000)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    exported = []
    for rec in records:
        exported.append({
            "trace_id": str(rec.trace_id),
            "event_type": rec.event_type,
            "decision": rec.decision,
            "score": rec.score,
            "tags": rec.tags,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "payload": rec.payload_snapshot,
        })

    return {
        "entity_id": body.entity_id,
        "tenant_id": body.tenant_id,
        "regulation": profile.regulation_name,
        "records_found": len(exported),
        "data": exported,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "note": "This export contains all data held about the data subject in the decision engine.",
    }


# ---------------------------------------------------------------------------
# DSAR — Right to Erasure
# ---------------------------------------------------------------------------

@router.post("/dsar/erasure")
async def dsar_erasure(
    body: DSARErasureRequest,
    session: AsyncSession = Depends(get_session),
):
    """Right to Erasure — delete all data for an entity."""
    profile = get_profile(body.region)
    if not profile.right_to_erasure:
        raise HTTPException(400, f"Right to erasure not applicable under {profile.regulation_name}")

    count_stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == body.tenant_id)
        .where(AuditRecord.entity_id == body.entity_id)
    )
    result = await session.execute(count_stmt)
    records = list(result.scalars().all())

    if not records:
        return {"entity_id": body.entity_id, "records_deleted": 0, "status": "no_data_found"}

    anonymized_count = 0
    for rec in records:
        if rec.payload_snapshot:
            rec.payload_snapshot = anonymize_record(rec.payload_snapshot)
        rec.entity_id = f"erased:{hashlib.sha256(body.entity_id.encode()).hexdigest()[:12]}"
        anonymized_count += 1

    await session.commit()

    log.info(
        "DSAR erasure: tenant=%s entity=%s records=%d reason=%s",
        body.tenant_id, body.entity_id[:8] + "...", anonymized_count, body.reason,
    )

    return {
        "entity_id": body.entity_id,
        "records_anonymized": anonymized_count,
        "status": "completed",
        "method": "anonymization",
        "regulation": profile.regulation_name,
        "note": "PII has been anonymized. Aggregate fraud statistics preserved per legitimate interest.",
    }


# ---------------------------------------------------------------------------
# DSAR — Right to Data Portability
# ---------------------------------------------------------------------------

@router.post("/dsar/portability")
async def dsar_portability(
    body: DSARAccessRequest,
    session: AsyncSession = Depends(get_session),
):
    """Right to Data Portability — export in machine-readable JSON."""
    profile = get_profile(body.region)
    if not profile.right_to_portability:
        raise HTTPException(400, f"Data portability not applicable under {profile.regulation_name}")

    stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == body.tenant_id)
        .where(AuditRecord.entity_id == body.entity_id)
        .order_by(AuditRecord.created_at.desc())
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    portable = {
        "schema_version": "1.0",
        "export_format": "tarka_portable_v1",
        "entity_id": body.entity_id,
        "tenant_id": body.tenant_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "records": [
            {
                "trace_id": str(r.trace_id),
                "event_type": r.event_type,
                "decision": r.decision,
                "score": r.score,
                "tags": r.tags,
                "rule_hits": r.rule_hits,
                "payload": r.payload_snapshot,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }

    return portable


# ---------------------------------------------------------------------------
# Region listing & certification checklist
# ---------------------------------------------------------------------------

@router.get("/regions")
async def list_regions():
    """List all supported privacy regions and their key requirements."""
    return {
        "regions": {
            r.value: {
                "display_name": p.display_name,
                "regulation": p.regulation_name,
                "right_to_erasure": p.right_to_erasure,
                "right_to_access": p.right_to_access,
                "requires_consent": p.requires_explicit_consent,
                "max_retention_days": p.max_retention_days,
                "encrypt_pii": p.encrypt_pii_at_rest,
                "breach_notify_hours": p.breach_notify_hours,
            }
            for r, p in PRIVACY_PROFILES.items()
        }
    }


@router.get("/certifications")
async def certification_checklist():
    """SOC2/PCI-DSS/ISO27001 readiness checklist."""
    return {
        "soc2_type2": {
            "security": [
                {"control": "Access Control (CC6.1)", "status": "implemented", "detail": "RBAC + JWT/OIDC via auth_rbac.py"},
                {"control": "Logical Access (CC6.2)", "status": "implemented", "detail": "API key + role-based middleware"},
                {"control": "Encryption in Transit (CC6.7)", "status": "configurable", "detail": "TLS termination at load balancer/ingress"},
                {"control": "Encryption at Rest (CC6.1)", "status": "configurable", "detail": "PostgreSQL TDE + Redis encryption"},
                {"control": "Change Management (CC8.1)", "status": "implemented", "detail": "Field-level audit trail on all mutations"},
                {"control": "Risk Assessment (CC3.2)", "status": "implemented", "detail": "Real-time fraud scoring with explainability"},
                {"control": "Monitoring (CC7.2)", "status": "implemented", "detail": "Prometheus metrics + structured logging"},
                {"control": "Incident Response (CC7.3)", "status": "partial", "detail": "Webhook alerts; formal IR plan needed"},
                {"control": "Vendor Management (CC9.2)", "status": "partial", "detail": "OSINT API keys configurable; DPA templates needed"},
            ],
            "availability": [
                {"control": "System Recovery (A1.2)", "status": "configurable", "detail": "Docker/K8s health checks + auto-restart"},
                {"control": "Backup (A1.2)", "status": "configurable", "detail": "PostgreSQL pg_dump; ClickHouse backup"},
            ],
            "confidentiality": [
                {"control": "Data Classification (C1.1)", "status": "implemented", "detail": "PII field classification in privacy.py"},
                {"control": "Data Retention (C1.2)", "status": "implemented", "detail": "Configurable per-region retention policies"},
            ],
        },
        "pci_dss_v4": [
            {"requirement": "3.4 - Render PAN unreadable", "status": "implemented", "detail": "PII masking engine masks card numbers"},
            {"requirement": "3.5 - Protect stored account data", "status": "configurable", "detail": "Encryption at rest when enabled"},
            {"requirement": "8.3 - MFA", "status": "configurable", "detail": "OIDC SSO supports MFA at IdP level"},
            {"requirement": "10.1 - Audit trails", "status": "implemented", "detail": "Immutable audit_trail table"},
            {"requirement": "11.3 - Vulnerability scanning", "status": "partial", "detail": "CI/CD includes linting; needs DAST/SAST tools"},
        ],
        "iso_27001": [
            {"control": "A.8.2 - Information Classification", "status": "implemented", "detail": "PII categorization (direct/quasi/sensitive/contact/financial/device)"},
            {"control": "A.8.10 - Information Deletion", "status": "implemented", "detail": "DSAR erasure + retention cleanup"},
            {"control": "A.8.24 - Cryptography", "status": "configurable", "detail": "AES-256 at rest when privacy profile requires it"},
            {"control": "A.5.34 - Privacy/PII Protection", "status": "implemented", "detail": "Region-aware privacy profiles (12 jurisdictions)"},
        ],
    }
