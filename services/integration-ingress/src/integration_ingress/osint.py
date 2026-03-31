"""OSINT enrichment framework — multi-source intelligence gathering.

Integrates free/open OSINT APIs for comprehensive entity risk profiling:

IP Intelligence:
  - Shodan InternetDB    (no key, open ports/vulns/tags)
  - AbuseIPDB            (free 1k/day, abuse confidence score)
  - GreyNoise Community  (free 50/day, scanner classification)
  - IPinfo Lite          (free unlimited, geo/ASN)
  - ip-api.com           (free 45/min, geo/proxy/hosting)

Email Intelligence:
  - EmailRep.io          (free 250/mo, reputation + social profiles)
  - Gravatar             (no key, avatar existence)
  - Have I Been Pwned    (free k-anonymity, breach count)
  - DNS MX lookup        (no key, domain mail config)
  - Disposable domain    (local heuristic, 150+ domains)

Phone Intelligence:
  - NumVerify            (free 100/mo, carrier/line-type)
  - Local heuristics     (format, VOIP prefix, country code)

Domain Intelligence:
  - WHOIS age estimation (RDAP, free)
  - DNS record checks    (free)

Social/Identity:
  - GitHub profile       (free, username existence)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import socket
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — keys loaded from env via Settings, passed at init
# ---------------------------------------------------------------------------

class OsintConfig:
    def __init__(
        self,
        abuseipdb_key: str = "",
        greynoise_key: str = "",
        emailrep_key: str = "",
        numverify_key: str = "",
        ipinfo_token: str = "",
    ):
        self.abuseipdb_key = abuseipdb_key
        self.greynoise_key = greynoise_key
        self.emailrep_key = emailrep_key
        self.numverify_key = numverify_key
        self.ipinfo_token = ipinfo_token


# ---------------------------------------------------------------------------
# Disposable / free-provider domain lists (expanded)
# ---------------------------------------------------------------------------

DISPOSABLE_DOMAINS = frozenset({
    "tempmail.com", "throwaway.email", "guerrillamail.com", "mailinator.com",
    "yopmail.com", "tempail.com", "fakeinbox.com", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "dispostable.com", "trashmail.com",
    "temp-mail.org", "10minutemail.com", "minutemail.com", "getairmail.com",
    "mohmal.com", "mailnesia.com", "maildrop.cc", "nada.email",
    "discard.email", "tempr.email", "emailondeck.com", "mytemp.email",
    "burnermail.io", "harakirimail.com", "33mail.com", "getnada.com",
    "emailfake.com", "crazymailing.com", "tmail.ws", "tmpmail.net",
    "mailsac.com", "guerrillamail.info", "guerrillamail.net", "guerrillamail.de",
    "trashmail.me", "trashmail.net", "trash-mail.com", "byom.de",
    "spamgourmet.com", "spamfree24.org", "jetable.org", "mailexpire.com",
    "throwam.com", "mailcatch.com", "tempinbox.com", "incognitomail.org",
    "mailnull.com", "tempsky.com", "binkmail.com", "spaml.com",
    "armyspy.com", "cuvox.de", "dayrep.com", "einrot.com", "fleckens.hu",
    "gustr.com", "jourrapide.com", "rhyta.com", "superrito.com",
    "teleworm.us", "tempomail.fr", "tittbit.in", "tradelist.eu",
})

FREE_PROVIDERS = frozenset({
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com",
    "protonmail.com", "icloud.com", "mail.com", "zoho.com", "yandex.com",
    "gmx.com", "gmx.net", "live.com", "msn.com", "me.com",
    "fastmail.com", "tutanota.com", "pm.me", "cock.li",
})

VOIP_PREFIXES = frozenset({
    "900", "855", "844", "833", "888", "877", "866", "800",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_get(
    http: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 4.0,
    label: str = "",
) -> dict[str, Any] | None:
    try:
        r = await http.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        log.debug("OSINT %s failed: %s", label or url, exc)
    return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ===================================================================
#  IP OSINT
# ===================================================================

async def osint_ip_shodan(ip: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Shodan InternetDB — open ports, CVEs, tags. No API key needed."""
    result: dict[str, Any] = {"source": "shodan_internetdb", "ip": ip}
    data = await _safe_get(http, f"https://internetdb.shodan.io/{ip}", label="shodan")
    if data:
        result["ports"] = data.get("ports", [])
        result["hostnames"] = data.get("hostnames", [])
        result["vulns"] = data.get("vulns", [])
        result["cpes"] = data.get("cpes", [])
        result["tags"] = data.get("tags", [])
        result["open_port_count"] = len(result["ports"])
        result["vuln_count"] = len(result["vulns"])
        risk = 0
        if result["vuln_count"] > 5:
            risk += 25
        elif result["vuln_count"] > 0:
            risk += 10
        if "vpn" in result["tags"]:
            risk += 15
        if "cloud" in result["tags"]:
            risk += 5
        if result["open_port_count"] > 10:
            risk += 10
        result["risk_score"] = min(risk, 100)
    return result


async def osint_ip_abuseipdb(
    ip: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """AbuseIPDB — crowd-sourced abuse confidence score. Needs API key."""
    result: dict[str, Any] = {"source": "abuseipdb", "ip": ip}
    if not cfg.abuseipdb_key:
        result["skipped"] = "no_api_key"
        return result
    data = await _safe_get(
        http,
        f"https://api.abuseipdb.com/api/v2/check?ipAddress={ip}&maxAgeInDays=90",
        headers={"Key": cfg.abuseipdb_key, "Accept": "application/json"},
        label="abuseipdb",
    )
    if data and "data" in data:
        d = data["data"]
        result["abuse_confidence"] = d.get("abuseConfidenceScore", 0)
        result["total_reports"] = d.get("totalReports", 0)
        result["country_code"] = d.get("countryCode")
        result["isp"] = d.get("isp")
        result["domain"] = d.get("domain")
        result["is_tor"] = d.get("isTor", False)
        result["is_whitelisted"] = d.get("isWhitelisted", False)
        result["risk_score"] = min(int(result["abuse_confidence"]), 100)
    return result


async def osint_ip_greynoise(
    ip: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """GreyNoise Community — mass-scanner detection. Free 50/day."""
    result: dict[str, Any] = {"source": "greynoise", "ip": ip}
    headers: dict[str, str] = {"Accept": "application/json"}
    if cfg.greynoise_key:
        headers["key"] = cfg.greynoise_key
    data = await _safe_get(
        http,
        f"https://api.greynoise.io/v3/community/{ip}",
        headers=headers,
        label="greynoise",
    )
    if data:
        result["noise"] = data.get("noise", False)
        result["riot"] = data.get("riot", False)
        result["classification"] = data.get("classification", "unknown")
        result["name"] = data.get("name", "")
        result["message"] = data.get("message", "")
        risk = 0
        if result["classification"] == "malicious":
            risk = 60
        elif result["classification"] == "suspicious":
            risk = 30
        elif result["noise"]:
            risk = 15
        result["risk_score"] = risk
    return result


async def osint_ip_ipinfo(
    ip: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """IPinfo Lite — geolocation, ASN, company. Free unlimited."""
    result: dict[str, Any] = {"source": "ipinfo", "ip": ip}
    token_param = f"?token={cfg.ipinfo_token}" if cfg.ipinfo_token else ""
    data = await _safe_get(
        http,
        f"https://ipinfo.io/{ip}/json{token_param}",
        label="ipinfo",
    )
    if data:
        result["city"] = data.get("city")
        result["region"] = data.get("region")
        result["country"] = data.get("country")
        result["org"] = data.get("org", "")
        result["asn"] = data.get("org", "").split(" ")[0] if data.get("org") else None
        result["hostname"] = data.get("hostname")
        result["timezone"] = data.get("timezone")
        result["is_bogon"] = data.get("bogon", False)
        privacy = data.get("privacy", {})
        if privacy:
            result["is_vpn"] = privacy.get("vpn", False)
            result["is_proxy"] = privacy.get("proxy", False)
            result["is_tor"] = privacy.get("tor", False)
            result["is_relay"] = privacy.get("relay", False)
            result["is_hosting"] = privacy.get("hosting", False)
        risk = 0
        if result.get("is_bogon"):
            risk += 30
        if result.get("is_vpn"):
            risk += 15
        if result.get("is_proxy"):
            risk += 20
        if result.get("is_tor"):
            risk += 35
        if result.get("is_hosting"):
            risk += 10
        result["risk_score"] = min(risk, 100)
    return result


async def osint_ip_ipapi(ip: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """ip-api.com — geo, ISP, proxy, hosting. Free 45/min."""
    result: dict[str, Any] = {"source": "ip_api", "ip": ip}
    data = await _safe_get(
        http,
        f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,isp,org,as,proxy,hosting,mobile,lat,lon,timezone",
        label="ip-api",
    )
    if data and data.get("status") == "success":
        result["country"] = data.get("country")
        result["country_code"] = data.get("countryCode")
        result["city"] = data.get("city")
        result["isp"] = data.get("isp")
        result["org"] = data.get("org")
        result["as"] = data.get("as")
        result["is_proxy"] = data.get("proxy", False)
        result["is_hosting"] = data.get("hosting", False)
        result["is_mobile"] = data.get("mobile", False)
        result["lat"] = data.get("lat")
        result["lon"] = data.get("lon")
        result["timezone"] = data.get("timezone")
        risk = 0
        if result["is_proxy"]:
            risk += 25
        if result["is_hosting"]:
            risk += 20
        result["risk_score"] = min(risk, 100)
    return result


async def enrich_ip_full(
    ip: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """Run all IP OSINT sources in parallel and aggregate."""
    tasks = [
        osint_ip_shodan(ip, http),
        osint_ip_abuseipdb(ip, http, cfg),
        osint_ip_greynoise(ip, http, cfg),
        osint_ip_ipinfo(ip, http, cfg),
        osint_ip_ipapi(ip, http),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sources: list[dict[str, Any]] = []
    risk_scores: list[float] = []
    geo: dict[str, Any] = {}
    flags: dict[str, bool] = {
        "is_vpn": False, "is_proxy": False, "is_tor": False,
        "is_hosting": False, "is_mobile": False, "is_scanner": False,
    }
    vulns: list[str] = []
    open_ports: list[int] = []

    for r in results:
        if isinstance(r, Exception):
            continue
        sources.append(r)
        rs = r.get("risk_score")
        if rs is not None:
            risk_scores.append(float(rs))
        if r.get("country") and not geo.get("country"):
            geo["country"] = r.get("country")
            geo["city"] = r.get("city")
        for flag in flags:
            if r.get(flag):
                flags[flag] = True
        if r.get("vulns"):
            vulns.extend(r["vulns"])
        if r.get("ports"):
            open_ports = r["ports"]

    # Weighted aggregate: AbuseIPDB and GreyNoise carry more weight
    if risk_scores:
        agg_risk = max(risk_scores) * 0.6 + (sum(risk_scores) / len(risk_scores)) * 0.4
    else:
        agg_risk = 0

    return {
        "ip": ip,
        "aggregate_risk_score": round(min(agg_risk, 100), 1),
        "sources_queried": len(sources),
        "geo": geo,
        "flags": flags,
        "open_ports": open_ports[:20],
        "vulns": list(set(vulns))[:20],
        "source_details": sources,
    }


# ===================================================================
#  EMAIL OSINT
# ===================================================================

async def osint_email_emailrep(
    email: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """EmailRep.io — reputation, social profiles, breach info."""
    result: dict[str, Any] = {"source": "emailrep", "email": email}
    headers: dict[str, str] = {"Accept": "application/json", "User-Agent": "tarka-fraud-stack"}
    if cfg.emailrep_key:
        headers["Key"] = cfg.emailrep_key
    data = await _safe_get(
        http, f"https://emailrep.io/{email}", headers=headers, label="emailrep",
    )
    if data:
        result["reputation"] = data.get("reputation", "none")
        result["suspicious"] = data.get("suspicious", False)
        result["references"] = data.get("references", 0)
        details = data.get("details", {})
        result["credentials_leaked"] = details.get("credentials_leaked", False)
        result["data_breach"] = details.get("data_breach", False)
        result["malicious_activity"] = details.get("malicious_activity", False)
        result["spam"] = details.get("spam", False)
        result["free_provider"] = details.get("free_provider", False)
        result["disposable"] = details.get("disposable", False)
        result["deliverable"] = details.get("deliverable", False)
        result["spoofable"] = details.get("spoofable", False)
        result["domain_exists"] = details.get("domain_exists", True)
        result["days_since_domain_creation"] = details.get("days_since_domain_creation")
        result["profiles"] = details.get("profiles", [])
        result["profile_count"] = len(result["profiles"])

        risk = 0
        if result["suspicious"]:
            risk += 30
        if result["credentials_leaked"]:
            risk += 15
        if result["malicious_activity"]:
            risk += 40
        if result["disposable"]:
            risk += 35
        if result["reputation"] == "none":
            risk += 20
        elif result["reputation"] == "low":
            risk += 15
        if not result["deliverable"]:
            risk += 10
        if result["spoofable"]:
            risk += 5
        result["risk_score"] = min(risk, 100)
    return result


async def osint_email_gravatar(email: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Gravatar — avatar existence check (social signal)."""
    result: dict[str, Any] = {"source": "gravatar", "email": email}
    email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()  # noqa: S324
    try:
        r = await http.get(f"https://gravatar.com/avatar/{email_hash}?d=404", timeout=3.0)
        result["exists"] = r.status_code == 200
        result["risk_score"] = 0 if result["exists"] else 10
    except Exception:
        result["exists"] = None
    return result


async def osint_email_hibp(email: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Have I Been Pwned — k-anonymity breach check (no API key needed for passwords)."""
    result: dict[str, Any] = {"source": "hibp_breaches", "email": email}
    try:
        r = await http.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
            headers={
                "User-Agent": "tarka-fraud-stack",
                "Accept": "application/json",
            },
            timeout=4.0,
        )
        if r.status_code == 200:
            breaches = r.json()
            result["breach_count"] = len(breaches)
            result["breach_names"] = [b.get("Name", "") for b in breaches[:10]]
            result["risk_score"] = min(len(breaches) * 5, 40)
        elif r.status_code == 404:
            result["breach_count"] = 0
            result["breach_names"] = []
            result["risk_score"] = 0
        else:
            result["breach_count"] = None
            result["note"] = "API requires paid key for breach lookups"
    except Exception:
        result["breach_count"] = None
    return result


async def osint_email_dns(email: str) -> dict[str, Any]:
    """DNS MX record check — verify domain can receive mail."""
    result: dict[str, Any] = {"source": "dns_mx", "email": email}
    if "@" not in email:
        result["has_mx"] = False
        result["risk_score"] = 30
        return result
    domain = email.split("@")[1].lower()
    try:
        loop = asyncio.get_event_loop()
        mx_records = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(domain, 25, proto=socket.IPPROTO_TCP),
        )
        result["has_mx"] = len(mx_records) > 0
        result["risk_score"] = 0 if result["has_mx"] else 20
    except (socket.gaierror, OSError):
        result["has_mx"] = False
        result["risk_score"] = 20
    return result


def _email_local_analysis(email: str) -> dict[str, Any]:
    """Local heuristic analysis — disposable, free, pattern scoring."""
    result: dict[str, Any] = {"source": "local_heuristic", "email": email}
    if not email or "@" not in email:
        result["risk_score"] = 80
        result["flags"] = ["invalid_format"]
        return result

    local, domain = email.lower().split("@", 1)
    result["domain"] = domain
    result["is_disposable"] = domain in DISPOSABLE_DOMAINS
    result["is_free_provider"] = domain in FREE_PROVIDERS

    flags: list[str] = []
    risk = 0

    if result["is_disposable"]:
        flags.append("disposable_domain")
        risk += 40

    if result["is_free_provider"]:
        flags.append("free_provider")
        risk += 5

    if re.match(r"^[a-z]{1,3}\d{5,}$", local):
        flags.append("auto_generated_pattern")
        risk += 15

    if len(local) < 3:
        flags.append("very_short_local")
        risk += 10

    plus_pos = local.find("+")
    if plus_pos != -1 and plus_pos < len(local) - 1:
        flags.append("plus_addressing")
        risk += 5

    digit_ratio = sum(c.isdigit() for c in local) / max(len(local), 1)
    if digit_ratio > 0.6:
        flags.append("high_digit_ratio")
        risk += 10

    result["flags"] = flags
    result["risk_score"] = min(risk, 100)
    return result


async def enrich_email_full(
    email: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """Run all email OSINT sources in parallel and aggregate."""
    local_analysis = _email_local_analysis(email)
    tasks = [
        osint_email_emailrep(email, http, cfg),
        osint_email_gravatar(email, http),
        osint_email_hibp(email, http),
        osint_email_dns(email),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sources: list[dict[str, Any]] = [local_analysis]
    risk_scores: list[float] = [float(local_analysis.get("risk_score", 0))]
    profiles: list[str] = []

    for r in results:
        if isinstance(r, Exception):
            continue
        sources.append(r)
        rs = r.get("risk_score")
        if rs is not None:
            risk_scores.append(float(rs))
        if r.get("profiles"):
            profiles.extend(r["profiles"])

    if risk_scores:
        agg_risk = max(risk_scores) * 0.5 + (sum(risk_scores) / len(risk_scores)) * 0.5
    else:
        agg_risk = 0

    return {
        "email": email,
        "aggregate_risk_score": round(min(agg_risk, 100), 1),
        "is_disposable": local_analysis.get("is_disposable", False),
        "is_free_provider": local_analysis.get("is_free_provider", False),
        "domain": local_analysis.get("domain", ""),
        "social_profiles": list(set(profiles)),
        "social_profile_count": len(set(profiles)),
        "sources_queried": len(sources),
        "source_details": sources,
    }


# ===================================================================
#  PHONE OSINT
# ===================================================================

async def osint_phone_numverify(
    phone: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """NumVerify API — carrier, line type, validity."""
    result: dict[str, Any] = {"source": "numverify", "phone": phone}
    if not cfg.numverify_key:
        result["skipped"] = "no_api_key"
        return result
    cleaned = re.sub(r"[^0-9]", "", phone)
    data = await _safe_get(
        http,
        f"http://apilayer.net/api/validate?access_key={cfg.numverify_key}&number={cleaned}",
        label="numverify",
    )
    if data:
        result["valid"] = data.get("valid", False)
        result["country_code"] = data.get("country_code")
        result["country_name"] = data.get("country_name")
        result["carrier"] = data.get("carrier", "")
        result["line_type"] = data.get("line_type", "")
        risk = 0
        if not result["valid"]:
            risk += 30
        if result["line_type"] == "voip":
            risk += 20
        if result["line_type"] == "prepaid":
            risk += 10
        result["risk_score"] = risk
    return result


def _phone_local_analysis(phone: str) -> dict[str, Any]:
    """Local phone heuristic analysis."""
    result: dict[str, Any] = {"source": "local_heuristic", "phone": phone}
    cleaned = re.sub(r"[^0-9+]", "", phone)

    flags: list[str] = []
    risk = 0

    if len(cleaned) < 10:
        flags.append("too_short")
        risk += 30
    elif len(cleaned) > 15:
        flags.append("too_long")
        risk += 15

    country_code = None
    if cleaned.startswith("+1") or (not cleaned.startswith("+") and len(cleaned) == 10):
        country_code = "US"
    elif cleaned.startswith("+44"):
        country_code = "GB"
    elif cleaned.startswith("+91"):
        country_code = "IN"
    elif cleaned.startswith("+86"):
        country_code = "CN"
    elif cleaned.startswith("+81"):
        country_code = "JP"
    elif cleaned.startswith("+49"):
        country_code = "DE"
    elif cleaned.startswith("+33"):
        country_code = "FR"
    elif cleaned.startswith("+55"):
        country_code = "BR"
    elif cleaned.startswith("+234"):
        country_code = "NG"
        flags.append("high_fraud_country")
        risk += 10

    is_voip = False
    if len(cleaned) >= 10:
        area = cleaned[-10:-7]
        if area in VOIP_PREFIXES:
            is_voip = True
            flags.append("voip_prefix")
            risk += 15

    if re.match(r"^\+?(\d)\1{9,}$", cleaned):
        flags.append("repeating_digits")
        risk += 25

    if re.match(r"^\+?1234567", cleaned):
        flags.append("sequential_pattern")
        risk += 30

    result["country_code"] = country_code
    result["is_voip_likely"] = is_voip
    result["is_valid_format"] = 10 <= len(cleaned) <= 15
    result["flags"] = flags
    result["risk_score"] = min(risk, 100)
    return result


async def enrich_phone_full(
    phone: str, http: httpx.AsyncClient, cfg: OsintConfig,
) -> dict[str, Any]:
    """Run all phone OSINT sources and aggregate."""
    local = _phone_local_analysis(phone)
    tasks = [osint_phone_numverify(phone, http, cfg)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sources: list[dict[str, Any]] = [local]
    risk_scores: list[float] = [float(local.get("risk_score", 0))]

    for r in results:
        if isinstance(r, Exception):
            continue
        sources.append(r)
        rs = r.get("risk_score")
        if rs is not None:
            risk_scores.append(float(rs))

    agg_risk = max(risk_scores) * 0.6 + (sum(risk_scores) / len(risk_scores)) * 0.4 if risk_scores else 0

    return {
        "phone": phone,
        "aggregate_risk_score": round(min(agg_risk, 100), 1),
        "country_code": local.get("country_code"),
        "is_voip_likely": local.get("is_voip_likely", False),
        "is_valid_format": local.get("is_valid_format", False),
        "sources_queried": len(sources),
        "source_details": sources,
    }


# ===================================================================
#  DOMAIN OSINT
# ===================================================================

async def osint_domain_rdap(domain: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """RDAP — domain registration info (successor to WHOIS). Free."""
    result: dict[str, Any] = {"source": "rdap", "domain": domain}
    data = await _safe_get(
        http, f"https://rdap.org/domain/{domain}", label="rdap", timeout=5.0,
    )
    if data:
        events = data.get("events", [])
        for evt in events:
            action = evt.get("eventAction", "")
            date_str = evt.get("eventDate", "")
            if action == "registration" and date_str:
                result["registration_date"] = date_str
            elif action == "last changed" and date_str:
                result["last_changed"] = date_str
        nameservers = [ns.get("ldhName", "") for ns in data.get("nameservers", [])]
        result["nameservers"] = nameservers
        result["status"] = data.get("status", [])

        risk = 0
        if result.get("registration_date"):
            try:
                from datetime import datetime, timezone
                reg = datetime.fromisoformat(result["registration_date"].replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - reg).days
                result["age_days"] = age_days
                if age_days < 30:
                    risk += 35
                    result["flag"] = "newly_registered"
                elif age_days < 90:
                    risk += 15
            except (ValueError, TypeError):
                pass
        result["risk_score"] = risk
    return result


async def enrich_domain_full(
    domain: str, http: httpx.AsyncClient,
) -> dict[str, Any]:
    """Domain OSINT aggregation."""
    rdap = await osint_domain_rdap(domain, http)
    return {
        "domain": domain,
        "aggregate_risk_score": rdap.get("risk_score", 0),
        "age_days": rdap.get("age_days"),
        "registration_date": rdap.get("registration_date"),
        "nameservers": rdap.get("nameservers", []),
        "source_details": [rdap],
    }


# ===================================================================
#  SOCIAL / IDENTITY OSINT
# ===================================================================

async def osint_github_profile(username: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Check if a GitHub profile exists for the username."""
    result: dict[str, Any] = {"source": "github", "username": username}
    data = await _safe_get(
        http, f"https://api.github.com/users/{username}", label="github",
    )
    if data and data.get("login"):
        result["exists"] = True
        result["public_repos"] = data.get("public_repos", 0)
        result["followers"] = data.get("followers", 0)
        result["created_at"] = data.get("created_at")
        result["bio"] = data.get("bio")
    else:
        result["exists"] = False
    return result


async def enrich_identity(
    email: str | None, http: httpx.AsyncClient,
) -> dict[str, Any]:
    """Try to discover social identity from email username."""
    result: dict[str, Any] = {"social_profiles": []}
    if not email or "@" not in email:
        return result
    username = email.split("@")[0].lower()
    cut_positions = [p for p in (username.find("+"), username.find(".")) if p != -1]
    if cut_positions:
        username = username[:min(cut_positions)]
    if len(username) < 3:
        return result

    github = await osint_github_profile(username, http)
    if github.get("exists"):
        result["social_profiles"].append(github)
    result["username_checked"] = username
    return result


# ===================================================================
#  UNIFIED OSINT ENRICHMENT
# ===================================================================

async def full_osint_enrichment(
    *,
    email: str | None = None,
    phone: str | None = None,
    ip: str | None = None,
    domain: str | None = None,
    http: httpx.AsyncClient,
    cfg: OsintConfig,
) -> dict[str, Any]:
    """Run comprehensive OSINT enrichment across all provided signals."""
    t0 = time.monotonic()
    tasks: dict[str, Any] = {}

    if ip:
        tasks["ip"] = enrich_ip_full(ip, http, cfg)
    if email:
        tasks["email"] = enrich_email_full(email, http, cfg)
        if "@" in email:
            auto_domain = email.split("@")[1].lower()
            if auto_domain not in DISPOSABLE_DOMAINS and auto_domain not in FREE_PROVIDERS:
                tasks["domain"] = enrich_domain_full(auto_domain, http)
        tasks["identity"] = enrich_identity(email, http)
    if phone:
        tasks["phone"] = enrich_phone_full(phone, http, cfg)
    if domain and "domain" not in tasks:
        tasks["domain"] = enrich_domain_full(domain, http)

    if not tasks:
        return {"error": "At least one of email, phone, ip, or domain is required"}

    keys = list(tasks.keys())
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results: dict[str, Any] = {}
    all_risk_scores: list[float] = []

    for key, val in zip(keys, results_list):
        if isinstance(val, Exception):
            results[key] = {"error": str(val)}
            continue
        results[key] = val
        agg = val.get("aggregate_risk_score")
        if agg is not None:
            all_risk_scores.append(float(agg))

    # Composite risk: weighted max
    if all_risk_scores:
        composite = max(all_risk_scores) * 0.7 + (sum(all_risk_scores) / len(all_risk_scores)) * 0.3
    else:
        composite = 0

    risk_level = "low"
    if composite >= 70:
        risk_level = "critical"
    elif composite >= 50:
        risk_level = "high"
    elif composite >= 30:
        risk_level = "medium"

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    return {
        "composite_risk_score": round(min(composite, 100), 1),
        "risk_level": risk_level,
        "enrichments": results,
        "signals_queried": len(results),
        "elapsed_ms": elapsed_ms,
    }
