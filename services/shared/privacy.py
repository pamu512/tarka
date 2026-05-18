from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

"""Region-aware privacy compliance framework.

Supports GDPR (EU), CCPA/CPRA (California), LGPD (Brazil), DPDP (India),
POPIA (South Africa), PDPA (Singapore/Thailand), APPI (Japan), PIPEDA (Canada),
and a baseline profile for regions without specific regulation.

Each profile controls:
- Data retention periods
- PII field classification
- Consent requirements
- Right to erasure scope
- Cross-border transfer rules
- Anonymization requirements
- Breach notification timelines
"""
log = logging.getLogger("tarka.privacy")


# ---------------------------------------------------------------------------
# Region enum & privacy profile
# ---------------------------------------------------------------------------


class Region(str, Enum):
    EU = "eu"  # GDPR
    US_CA = "us_ca"  # CCPA/CPRA
    US = "us"  # General US (no federal privacy law)
    BR = "br"  # LGPD
    IN = "in"  # DPDP Act
    ZA = "za"  # POPIA
    SG = "sg"  # PDPA
    JP = "jp"  # APPI
    CA = "ca"  # PIPEDA
    UK = "uk"  # UK GDPR
    AU = "au"  # Privacy Act
    GLOBAL = "global"  # Baseline


@dataclass
class PrivacyProfile:
    region: Region
    display_name: str
    regulation_name: str

    # Retention
    max_retention_days: int = 365 * 7  # default 7 years (AML typical)
    pii_retention_days: int = 365 * 3  # PII specifically
    audit_retention_days: int = 365 * 5

    # Consent
    requires_explicit_consent: bool = False
    consent_for_profiling: bool = False
    consent_for_automated_decisions: bool = False
    right_to_opt_out_of_sale: bool = False

    # Data subject rights
    right_to_access: bool = True
    right_to_erasure: bool = False
    right_to_portability: bool = False
    right_to_rectification: bool = False
    right_to_restrict_processing: bool = False
    right_to_object: bool = False

    # Anonymization
    anonymize_after_retention: bool = False
    pseudonymize_at_rest: bool = False
    mask_pii_in_logs: bool = True
    mask_pii_in_responses: bool = False

    # Cross-border
    restrict_cross_border: bool = False
    adequacy_required: bool = False

    # Breach notification
    breach_notify_hours: int = 72
    breach_notify_authority: bool = False
    breach_notify_subjects: bool = False

    # Encryption
    encrypt_pii_at_rest: bool = False
    min_encryption_standard: str = "AES-256"


PRIVACY_PROFILES: dict[Region, PrivacyProfile] = {
    Region.EU: PrivacyProfile(
        region=Region.EU,
        display_name="European Union",
        regulation_name="GDPR",
        max_retention_days=365 * 5,
        pii_retention_days=365 * 3,
        requires_explicit_consent=True,
        consent_for_profiling=True,
        consent_for_automated_decisions=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_portability=True,
        right_to_rectification=True,
        right_to_restrict_processing=True,
        right_to_object=True,
        anonymize_after_retention=True,
        pseudonymize_at_rest=True,
        mask_pii_in_logs=True,
        mask_pii_in_responses=False,
        restrict_cross_border=True,
        adequacy_required=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
        breach_notify_subjects=True,
        encrypt_pii_at_rest=True,
    ),
    Region.UK: PrivacyProfile(
        region=Region.UK,
        display_name="United Kingdom",
        regulation_name="UK GDPR",
        max_retention_days=365 * 5,
        pii_retention_days=365 * 3,
        requires_explicit_consent=True,
        consent_for_profiling=True,
        consent_for_automated_decisions=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_portability=True,
        right_to_rectification=True,
        right_to_restrict_processing=True,
        right_to_object=True,
        anonymize_after_retention=True,
        pseudonymize_at_rest=True,
        mask_pii_in_logs=True,
        restrict_cross_border=True,
        adequacy_required=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
        breach_notify_subjects=True,
        encrypt_pii_at_rest=True,
    ),
    Region.US_CA: PrivacyProfile(
        region=Region.US_CA,
        display_name="California",
        regulation_name="CCPA/CPRA",
        max_retention_days=365 * 7,
        pii_retention_days=365 * 3,
        right_to_opt_out_of_sale=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_portability=False,
        right_to_rectification=True,
        mask_pii_in_logs=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
    ),
    Region.BR: PrivacyProfile(
        region=Region.BR,
        display_name="Brazil",
        regulation_name="LGPD",
        requires_explicit_consent=True,
        consent_for_profiling=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_portability=True,
        right_to_rectification=True,
        anonymize_after_retention=True,
        restrict_cross_border=True,
        adequacy_required=True,
        breach_notify_authority=True,
        encrypt_pii_at_rest=True,
    ),
    Region.IN: PrivacyProfile(
        region=Region.IN,
        display_name="India",
        regulation_name="DPDP Act 2023",
        requires_explicit_consent=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_rectification=True,
        restrict_cross_border=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
        encrypt_pii_at_rest=True,
    ),
    Region.SG: PrivacyProfile(
        region=Region.SG,
        display_name="Singapore",
        regulation_name="PDPA",
        requires_explicit_consent=True,
        right_to_access=True,
        right_to_rectification=True,
        restrict_cross_border=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
    ),
    Region.JP: PrivacyProfile(
        region=Region.JP,
        display_name="Japan",
        regulation_name="APPI",
        requires_explicit_consent=True,
        consent_for_profiling=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_rectification=True,
        restrict_cross_border=True,
        adequacy_required=True,
        breach_notify_authority=True,
    ),
    Region.CA: PrivacyProfile(
        region=Region.CA,
        display_name="Canada",
        regulation_name="PIPEDA",
        requires_explicit_consent=True,
        right_to_access=True,
        right_to_rectification=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
        breach_notify_subjects=True,
    ),
    Region.ZA: PrivacyProfile(
        region=Region.ZA,
        display_name="South Africa",
        regulation_name="POPIA",
        requires_explicit_consent=True,
        right_to_access=True,
        right_to_erasure=True,
        right_to_rectification=True,
        right_to_object=True,
        restrict_cross_border=True,
        breach_notify_authority=True,
    ),
    Region.AU: PrivacyProfile(
        region=Region.AU,
        display_name="Australia",
        regulation_name="Privacy Act 1988",
        right_to_access=True,
        right_to_rectification=True,
        breach_notify_hours=72,
        breach_notify_authority=True,
    ),
    Region.US: PrivacyProfile(
        region=Region.US,
        display_name="United States (Federal)",
        regulation_name="No federal privacy law",
        max_retention_days=365 * 7,
        audit_retention_days=365 * 7,
    ),
    Region.GLOBAL: PrivacyProfile(
        region=Region.GLOBAL,
        display_name="Global Baseline",
        regulation_name="Tarka Default",
        mask_pii_in_logs=True,
    ),
}


def get_profile(region: str | Region) -> PrivacyProfile:
    """Return the privacy profile for *region*, falling back to GLOBAL."""
    if isinstance(region, str):
        try:
            region = Region(region.lower())
        except ValueError:
            region = Region.GLOBAL
    return PRIVACY_PROFILES.get(region, PRIVACY_PROFILES[Region.GLOBAL])


# ---------------------------------------------------------------------------
# PII field classification
# ---------------------------------------------------------------------------


class PIICategory(str, Enum):
    DIRECT = "direct"  # Name, SSN, passport
    QUASI = "quasi"  # DOB, zip, gender (can re-identify in combination)
    SENSITIVE = "sensitive"  # Race, religion, health, biometric
    CONTACT = "contact"  # Email, phone, address
    FINANCIAL = "financial"  # Card number, bank account, income
    DEVICE = "device"  # Device ID, IP, fingerprint
    BEHAVIORAL = "behavioral"  # Browsing history, purchase patterns


PII_FIELDS: dict[str, PIICategory] = {
    # Direct identifiers
    "name": PIICategory.DIRECT,
    "first_name": PIICategory.DIRECT,
    "last_name": PIICategory.DIRECT,
    "full_name": PIICategory.DIRECT,
    "ssn": PIICategory.DIRECT,
    "social_security": PIICategory.DIRECT,
    "passport": PIICategory.DIRECT,
    "passport_number": PIICategory.DIRECT,
    "national_id": PIICategory.DIRECT,
    "driver_license": PIICategory.DIRECT,
    # Contact
    "email": PIICategory.CONTACT,
    "email_address": PIICategory.CONTACT,
    "phone": PIICategory.CONTACT,
    "phone_number": PIICategory.CONTACT,
    "address": PIICategory.CONTACT,
    "street": PIICategory.CONTACT,
    "zip_code": PIICategory.CONTACT,
    "postal_code": PIICategory.CONTACT,
    # Financial
    "card_number": PIICategory.FINANCIAL,
    "credit_card": PIICategory.FINANCIAL,
    "bank_account": PIICategory.FINANCIAL,
    "iban": PIICategory.FINANCIAL,
    "routing_number": PIICategory.FINANCIAL,
    "account_number": PIICategory.FINANCIAL,
    "income": PIICategory.FINANCIAL,
    # Quasi-identifiers
    "date_of_birth": PIICategory.QUASI,
    "dob": PIICategory.QUASI,
    "age": PIICategory.QUASI,
    "gender": PIICategory.QUASI,
    "zip": PIICategory.QUASI,
    # Device
    "ip": PIICategory.DEVICE,
    "ip_address": PIICategory.DEVICE,
    "device_id": PIICategory.DEVICE,
    "fingerprint": PIICategory.DEVICE,
    "mac_address": PIICategory.DEVICE,
    "user_agent": PIICategory.DEVICE,
    # Sensitive
    "race": PIICategory.SENSITIVE,
    "ethnicity": PIICategory.SENSITIVE,
    "religion": PIICategory.SENSITIVE,
    "health_status": PIICategory.SENSITIVE,
    "biometric": PIICategory.SENSITIVE,
}

PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\+?\d[\d\-\s]{8,15}"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "ipv4": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}


# ---------------------------------------------------------------------------
# PII detection, masking, and anonymization helpers
# ---------------------------------------------------------------------------


def classify_field(field_name: str) -> PIICategory | None:
    """Return the PII category for a known field name, or ``None``."""
    normalized = field_name.lower().replace("-", "_")
    return PII_FIELDS.get(normalized)


def detect_pii_in_value(value: str) -> list[str]:
    """Detect PII patterns in a string value."""
    found = []
    for name, pattern in PII_PATTERNS.items():
        if pattern.search(str(value)):
            found.append(name)
    return found


def mask_value(value: Any, category: PIICategory | None = None) -> Any:
    """Mask a PII value based on its category."""
    if value is None:
        return None
    s = str(value)
    if not s:
        return s

    if category == PIICategory.FINANCIAL:
        if len(s) > 4:
            return "****" + s[-4:]
        return "****"

    if category == PIICategory.DIRECT:
        return "***REDACTED***"

    if category == PIICategory.CONTACT:
        if "@" in s:
            local, domain = s.split("@", 1)
            return local[:2] + "***@" + domain
        if len(s) > 4:
            return s[:2] + "*" * (len(s) - 4) + s[-2:]
        return "****"

    if category in (PIICategory.DEVICE, PIICategory.QUASI):
        return "hash:" + hashlib.sha256(s.encode()).hexdigest()[:12]

    if category == PIICategory.SENSITIVE:
        return "***SENSITIVE***"

    # Default: partial mask
    if len(s) > 4:
        return s[:2] + "*" * (len(s) - 4) + s[-2:]
    return "****"


def pseudonymize_value(value: Any, salt: str = "") -> str:
    """Create a consistent pseudonym via HMAC-SHA256."""
    s = str(value) if value is not None else ""
    return "pseudo:" + hashlib.sha256((salt + s).encode()).hexdigest()[:16]


def mask_dict(
    data: dict[str, Any],
    profile: PrivacyProfile | None = None,
) -> dict[str, Any]:
    """Mask PII fields in a dictionary based on privacy profile."""
    if not profile:
        profile = PRIVACY_PROFILES[Region.GLOBAL]

    if not profile.mask_pii_in_logs and not profile.mask_pii_in_responses:
        return data

    masked: dict[str, Any] = {}
    for key, value in data.items():
        category = classify_field(key)
        if category and (profile.mask_pii_in_logs or profile.mask_pii_in_responses):
            if profile.pseudonymize_at_rest:
                masked[key] = pseudonymize_value(value)
            else:
                masked[key] = mask_value(value, category)
        elif isinstance(value, dict):
            masked[key] = mask_dict(value, profile)
        else:
            masked[key] = value
    return masked


def anonymize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Fully anonymize a record (irreversible). Used when retention expires."""
    anon: dict[str, Any] = {}
    for key, value in record.items():
        category = classify_field(key)
        if category:
            anon[key] = hashlib.sha256(str(value).encode()).hexdigest()[:8] if value else None
        elif isinstance(value, dict):
            anon[key] = anonymize_record(value)
        else:
            anon[key] = value
    return anon


# ---------------------------------------------------------------------------
# Article 30 GDPR-style Record of Processing Activities
# ---------------------------------------------------------------------------


def get_data_processing_record(
    tenant_id: str,
    profile: PrivacyProfile,
) -> dict[str, Any]:
    """Generate an Article 30 GDPR-style Record of Processing Activities."""
    return {
        "controller": tenant_id,
        "processor": "Tarka Fraud Detection Platform",
        "purposes": [
            "Fraud prevention and detection",
            "Anti-money laundering compliance",
            "Risk scoring and decisioning",
            "Investigation and case management",
        ],
        "data_subjects": ["Customers", "Users", "Account holders"],
        "data_categories": [
            "Transaction data",
            "Device and browser data",
            "IP address and geolocation",
            "Email and phone (for enrichment)",
            "Behavioral biometrics",
        ],
        "recipients": [
            "Internal fraud analysts",
            "Compliance officers",
            "Law enforcement (upon legal request)",
        ],
        "retention": {
            "transaction_data": f"{profile.max_retention_days} days",
            "pii_data": f"{profile.pii_retention_days} days",
            "audit_logs": f"{profile.audit_retention_days} days",
        },
        "cross_border_transfers": "Restricted" if profile.restrict_cross_border else "Permitted",
        "security_measures": [
            "Encryption at rest (AES-256)"
            if profile.encrypt_pii_at_rest
            else "Standard database security",
            "TLS 1.3 in transit",
            "RBAC access control",
            "Field-level audit trail",
            "PII masking in logs",
        ],
        "regulation": profile.regulation_name,
        "region": profile.display_name,
    }
