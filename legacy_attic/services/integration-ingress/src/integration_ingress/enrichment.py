"""Digital footprint and signal enrichment.

Provides email, phone, and IP enrichment using free/open APIs and heuristics.
"""

import hashlib
import re
from typing import Any

import httpx

DISPOSABLE_DOMAINS = frozenset(
    {
        "tempmail.com",
        "throwaway.email",
        "guerrillamail.com",
        "mailinator.com",
        "yopmail.com",
        "tempail.com",
        "fakeinbox.com",
        "sharklasers.com",
        "guerrillamailblock.com",
        "grr.la",
        "dispostable.com",
        "trashmail.com",
    }
)

FREE_PROVIDERS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "aol.com",
        "protonmail.com",
        "icloud.com",
        "mail.com",
        "zoho.com",
        "yandex.com",
    }
)

VOIP_PREFIXES = frozenset(
    {
        "900",
        "855",
        "844",
        "833",
        "888",
        "877",
        "866",
        "800",
    }
)


async def enrich_email(email: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Enrich an email address with risk signals."""
    result: dict[str, Any] = {
        "email": email,
        "is_disposable": False,
        "is_free_provider": False,
        "domain": "",
        "domain_age_days": None,
        "has_mx_record": None,
        "gravatar_exists": False,
        "risk_score": 0,
    }

    if not email or "@" not in email:
        result["risk_score"] = 80
        return result

    domain = email.split("@")[1].lower()
    result["domain"] = domain

    if domain in DISPOSABLE_DOMAINS:
        result["is_disposable"] = True
        result["risk_score"] += 40

    if domain in FREE_PROVIDERS:
        result["is_free_provider"] = True
        result["risk_score"] += 5

    try:
        email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()  # noqa: S324
        r = await http.get(
            f"https://gravatar.com/avatar/{email_hash}?d=404",
            timeout=3.0,
        )
        result["gravatar_exists"] = r.status_code == 200
        if not result["gravatar_exists"]:
            result["risk_score"] += 10
    except Exception:
        pass

    return result


async def enrich_phone(phone: str) -> dict[str, Any]:
    """Basic phone number analysis (no external API needed)."""
    result: dict[str, Any] = {
        "phone": phone,
        "is_valid_format": False,
        "country_code": None,
        "is_voip_likely": False,
        "risk_score": 0,
    }

    cleaned = re.sub(r"[^0-9+]", "", phone)
    if len(cleaned) >= 10:
        result["is_valid_format"] = True
    else:
        result["risk_score"] += 30

    if cleaned.startswith("+1"):
        result["country_code"] = "US"
    elif cleaned.startswith("+44"):
        result["country_code"] = "UK"
    elif cleaned.startswith("+91"):
        result["country_code"] = "IN"

    if len(cleaned) >= 10 and cleaned[-10:-7] in VOIP_PREFIXES:
        result["is_voip_likely"] = True
        result["risk_score"] += 15

    return result


async def enrich_ip(ip: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """IP enrichment using free ip-api.com."""
    result: dict[str, Any] = {
        "ip": ip,
        "country": None,
        "city": None,
        "isp": None,
        "is_proxy": False,
        "is_hosting": False,
        "risk_score": 0,
    }

    try:
        r = await http.get(
            f"http://ip-api.com/json/{ip}?fields=status,country,city,isp,proxy,hosting",
            timeout=3.0,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                result["country"] = data.get("country")
                result["city"] = data.get("city")
                result["isp"] = data.get("isp")
                result["is_proxy"] = data.get("proxy", False)
                result["is_hosting"] = data.get("hosting", False)
                if result["is_proxy"]:
                    result["risk_score"] += 25
                if result["is_hosting"]:
                    result["risk_score"] += 20
    except Exception:
        pass

    return result
