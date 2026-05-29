"""Synthetic identity detectors — high-risk IP / browser / email combinations (Prompt 181)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_FLAG_SCORE = 70
DEFAULT_SCAN_LIMIT = 50


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _signal_tier(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _ip_signal(seed: str) -> dict[str, Any]:
    bucket = int(seed[0:2], 16) % 10
    patterns = [
        ("low", "Residential ISP", "Geo consistent with billing address"),
        ("medium", "Mobile carrier NAT", "Shared CGNAT pool — monitor velocity"),
        ("high", "Datacenter ASN", "Hosting provider IP (AS396982)"),
        ("high", "VPN exit node", "Commercial VPN fingerprint (Mullvad-class)"),
        ("high", "Tor exit", "Known Tor exit relay cluster"),
        ("medium", "Geo mismatch", "Login country ≠ card BIN country"),
        ("high", "Bulletproof host", "High-risk bulletproof hosting range"),
        ("medium", "Proxy chain", "Residential proxy marketplace signature"),
        ("high", "Fresh /24 block", "IP block first seen < 72h ago"),
        ("medium", "Velocity spike", "12 distinct entities on same /24 in 24h"),
    ]
    tier, label, detail = patterns[bucket]
    score = {"low": 25, "medium": 55, "high": 88}[tier]
    return {"risk": tier, "label": label, "detail": detail, "score": score}


def _browser_signal(seed: str) -> dict[str, Any]:
    bucket = int(seed[2:4], 16) % 10
    patterns = [
        ("low", "Mainstream Chrome", "Canvas/WebGL consistent with OS"),
        ("medium", "Safari iOS", "Minor timezone drift vs IP geo"),
        ("high", "Headless Chrome", "navigator.webdriver + automation flags"),
        ("high", "Android emulator", "Build fingerprint matches SDK emulator"),
        ("high", "Canvas hash collision", "Identical canvas hash across 8+ accounts"),
        ("medium", "Rare UA rotation", "4 user-agents in 10 minutes same session"),
        ("high", "WebGL spoof", "Renderer string inconsistent with platform"),
        ("medium", "Privacy browser", "Brave/Firefox hardening — limited signals"),
        ("high", "VM sandbox", "VirtualBox/VMware GPU strings in WebGL"),
        ("high", "Bot framework", "Puppeteer/Playwright runtime markers"),
    ]
    tier, label, detail = patterns[bucket]
    score = {"low": 20, "medium": 50, "high": 90}[tier]
    return {"risk": tier, "label": label, "detail": detail, "score": score}


def _email_signal(seed: str) -> dict[str, Any]:
    bucket = int(seed[4:6], 16) % 10
    patterns = [
        ("low", "Established domain", "MX > 2y, no disposable pattern"),
        ("medium", "Free provider", "Gmail — normal for retail cohort"),
        ("high", "Disposable inbox", "10minutemail-class domain"),
        ("high", "Plus-alias farm", "47 variants on same base mailbox"),
        ("high", "Domain age < 7d", "WHOIS created last week"),
        ("medium", "Typo-squat domain", "paypa1.com lookalike registrar"),
        ("high", "Breach replay", "Credential from 2024 combo list"),
        ("medium", "Role account", "support@ / noreply@ on consumer signup"),
        ("high", "Unicode homoglyph", "Cyrillic 'а' in local-part"),
        ("high", "Sequential pattern", "user+001..user+040 same domain"),
    ]
    tier, label, detail = patterns[bucket]
    score = {"low": 15, "medium": 48, "high": 92}[tier]
    return {"risk": tier, "label": label, "detail": detail, "score": score}


def _combo_flags(ip: dict[str, Any], browser: dict[str, Any], email: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if ip.get("risk") == "high" and email.get("risk") == "high":
        flags.append("ip_email_high_risk_combo")
    if browser.get("risk") == "high" and email.get("risk") == "high":
        flags.append("browser_email_high_risk_combo")
    if ip.get("risk") == "high" and browser.get("risk") == "high":
        flags.append("ip_browser_high_risk_combo")
    if ip.get("risk") == "high" and browser.get("risk") == "high" and email.get("risk") == "high":
        flags.append("synthetic_identity_triple")
    return flags


def _user_row(index: int, *, tenant_id: str) -> dict[str, Any]:
    seed = hashlib.sha256(f"{tenant_id}:syn_id:{index}".encode()).hexdigest()
    ip = _ip_signal(seed)
    browser = _browser_signal(seed)
    email = _email_signal(seed)
    risk_score = min(
        100,
        round(
            0.35 * int(ip["score"]) + 0.35 * int(browser["score"]) + 0.30 * int(email["score"]),
        ),
    )
    combo = _combo_flags(ip, browser, email)
    flagged = risk_score >= DEFAULT_FLAG_SCORE or "synthetic_identity_triple" in combo
    detected = datetime.now(UTC) - timedelta(hours=index * 2.7 + 1)
    return {
        "user_id": f"syn_user_{seed[:10]}",
        "entity_id": f"ent_{seed[10:18]}",
        "display_name": f"Signup cohort {index + 1}",
        "email": f"user{index}+{seed[6:10]}@{'maildrop.demo' if email['risk'] == 'high' else 'example-retail.com'}",
        "risk_score": risk_score,
        "is_synthetic_identity": flagged,
        "signals": {"ip": ip, "browser": browser, "email": email},
        "combo_flags": combo,
        "detected_at": detected.isoformat(),
    }


def build_synthetic_identity_payload(
    *,
    tenant_id: str,
    limit: int = DEFAULT_SCAN_LIMIT,
    flag_score: int = DEFAULT_FLAG_SCORE,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    lim = max(5, min(int(limit), 200))
    threshold = max(40, min(int(flag_score), 95))

    users = [_user_row(i, tenant_id=tid) for i in range(lim)]
    for u in users:
        u["is_synthetic_identity"] = bool(
            u["risk_score"] >= threshold
            or "synthetic_identity_triple" in (u.get("combo_flags") or []),
        )

    flagged = [u for u in users if u["is_synthetic_identity"]]
    triple = sum(1 for u in users if "synthetic_identity_triple" in (u.get("combo_flags") or []))

    users_sorted = sorted(
        users,
        key=lambda u: (-int(u["risk_score"]), str(u["user_id"])),
    )

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "thresholds": {"flag_score": threshold},
        "summary": {
            "scanned_users": len(users),
            "flagged_users": len(flagged),
            "triple_high_combos": triple,
            "avg_risk_score": round(
                sum(int(u["risk_score"]) for u in users) / max(len(users), 1), 1
            ),
        },
        "users": users_sorted,
    }
