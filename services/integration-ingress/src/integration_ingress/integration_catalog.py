from __future__ import annotations

from typing import Any


PROVIDER_CATALOG: list[dict[str, Any]] = [
    {"id": "onfido", "name": "Onfido", "category": "kyc", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://documentation.onfido.com/"},
    {"id": "sumsub", "name": "Sumsub", "category": "kyc", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://developers.sumsub.com/"},
    {"id": "fingerprint", "name": "Fingerprint", "category": "device_intelligence", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://dev.fingerprint.com/"},
    {"id": "threatmetrix", "name": "ThreatMetrix", "category": "device_intelligence", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://risk.lexisnexis.com/products/threatmetrix"},
    {"id": "maxmind", "name": "MaxMind minFraud", "category": "ip_intelligence", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://dev.maxmind.com/minfraud/"},
    {"id": "ipqs", "name": "IPQualityScore", "category": "ip_intelligence", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.ipqualityscore.com/documentation"},
    {"id": "telesign", "name": "Telesign", "category": "phone_number", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://developer.telesign.com/"},
    {"id": "twilio_lookup", "name": "Twilio Lookup", "category": "phone_number", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.twilio.com/docs/lookup"},
    {"id": "seon", "name": "SEON", "category": "social_media", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://docs.seon.io/"},
    {"id": "sociallinks", "name": "Social Links", "category": "social_media", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://sociallinks.io/"},
    {"id": "complyadvantage", "name": "ComplyAdvantage", "category": "sanctions", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://docs.complyadvantage.com/"},
    {"id": "dow_jones_riskcenter", "name": "Dow Jones RiskCenter", "category": "sanctions", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.dowjones.com/professional/risk/"},
    {"id": "stripe_radar", "name": "Stripe Radar", "category": "payments", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://stripe.com/docs/radar"},
    {"id": "adyen_protect", "name": "Adyen Protect", "category": "payments", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://docs.adyen.com/risk-management/"},
    {"id": "verifi", "name": "Verifi", "category": "dispute_management", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.verifi.com/"},
    {"id": "ethoca", "name": "Ethoca", "category": "dispute_management", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.ethoca.com/"},
    {"id": "verifi_cd_rdr", "name": "Verifi CDRN/RDR", "category": "early_alerts", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.verifi.com/"},
    {"id": "ethoca_alerts", "name": "Ethoca Alerts", "category": "early_alerts", "type": "api", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://www.ethoca.com/"},
    {"id": "jira", "name": "Jira", "category": "crm", "type": "saas", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://developer.atlassian.com/cloud/jira/platform/"},
    {"id": "salesforce", "name": "Salesforce", "category": "crm", "type": "saas", "required_config_fields": ["api_key", "username", "password"], "doc_url": "https://developer.salesforce.com/docs/apis"},
]


def list_categories() -> list[str]:
    return sorted({str(p["category"]) for p in PROVIDER_CATALOG})


def get_provider(provider_id: str) -> dict[str, Any] | None:
    target = provider_id.strip().lower()
    for item in PROVIDER_CATALOG:
        if str(item.get("id", "")).lower() == target:
            return item
    return None
