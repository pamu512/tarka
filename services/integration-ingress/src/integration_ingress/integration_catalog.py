from __future__ import annotations

from typing import Any

# Module swimlane label for GitHub project #3 (Integrations / platform); link is informational.
_SWIMLANE_INTEGRATE = "J1 — Integrate"
_GITHUB_PROJECT_VIEW = "https://github.com/users/pamu512/projects/3"


def _p(
    pid: str,
    name: str,
    category: str,
    *,
    fields: list[str] | None = None,
    doc_url: str,
    swimlane_module: str = _SWIMLANE_INTEGRATE,
) -> dict[str, Any]:
    return {
        "id": pid,
        "name": name,
        "category": category,
        "type": "api",
        "required_config_fields": fields or ["api_key", "username", "password"],
        "doc_url": doc_url,
        "swimlane_module": swimlane_module,
        "github_project_view_url": _GITHUB_PROJECT_VIEW,
    }


PROVIDER_CATALOG: list[dict[str, Any]] = [
    _p("onfido", "Onfido", "kyc", doc_url="https://documentation.onfido.com/"),
    _p("sumsub", "Sumsub", "kyc", doc_url="https://developers.sumsub.com/"),
    _p("fingerprint", "Fingerprint", "device_intelligence", doc_url="https://dev.fingerprint.com/"),
    _p(
        "threatmetrix",
        "ThreatMetrix",
        "device_intelligence",
        doc_url="https://risk.lexisnexis.com/products/threatmetrix",
    ),
    _p("maxmind", "MaxMind minFraud", "ip_intelligence", doc_url="https://dev.maxmind.com/minfraud/"),
    _p(
        "ipqs",
        "IPQualityScore",
        "ip_intelligence",
        doc_url="https://www.ipqualityscore.com/documentation",
    ),
    _p("telesign", "Telesign", "phone_number", doc_url="https://developer.telesign.com/"),
    _p(
        "twilio_lookup",
        "Twilio Lookup",
        "phone_number",
        doc_url="https://www.twilio.com/docs/lookup",
    ),
    _p("seon", "SEON", "social_media", doc_url="https://docs.seon.io/"),
    _p("sociallinks", "Social Links", "social_media", doc_url="https://sociallinks.io/"),
    _p(
        "complyadvantage",
        "ComplyAdvantage",
        "sanctions",
        doc_url="https://docs.complyadvantage.com/",
    ),
    _p(
        "opensanctions",
        "OpenSanctions",
        "sanctions",
        fields=["api_key"],
        doc_url="https://www.opensanctions.org/docs/api/",
    ),
    _p(
        "dow_jones_riskcenter",
        "Dow Jones RiskCenter",
        "sanctions",
        doc_url="https://www.dowjones.com/professional/risk/",
    ),
    _p("stripe_radar", "Stripe Radar", "payments", doc_url="https://stripe.com/docs/radar"),
    _p(
        "adyen_protect",
        "Adyen Protect",
        "payments",
        doc_url="https://docs.adyen.com/risk-management/",
    ),
    _p("verifi", "Verifi", "dispute_management", doc_url="https://www.verifi.com/"),
    _p("ethoca", "Ethoca", "dispute_management", doc_url="https://www.ethoca.com/"),
    _p("verifi_cd_rdr", "Verifi CDRN/RDR", "early_alerts", doc_url="https://www.verifi.com/"),
    _p("ethoca_alerts", "Ethoca Alerts", "early_alerts", doc_url="https://www.ethoca.com/"),
    _p(
        "jira",
        "Jira",
        "crm",
        doc_url="https://developer.atlassian.com/cloud/jira/platform/",
    ),
    _p(
        "salesforce",
        "Salesforce",
        "crm",
        doc_url="https://developer.salesforce.com/docs/apis",
    ),
]


def list_categories() -> list[str]:
    return sorted({str(p["category"]) for p in PROVIDER_CATALOG})


def get_provider(provider_id: str) -> dict[str, Any] | None:
    target = provider_id.strip().lower()
    for p in PROVIDER_CATALOG:
        if str(p["id"]).lower() == target:
            return p
    return None
