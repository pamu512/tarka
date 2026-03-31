"""Server-side CAPTCHA token verification for reCAPTCHA, hCaptcha, and Turnstile."""
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/captcha", tags=["captcha"])

RECAPTCHA_SECRET = os.environ.get("RECAPTCHA_SECRET_KEY", "")
HCAPTCHA_SECRET = os.environ.get("HCAPTCHA_SECRET_KEY", "")
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET_KEY", "")

VERIFY_URLS = {
    "recaptcha_v2": "https://www.google.com/recaptcha/api/siteverify",
    "recaptcha_v3": "https://www.google.com/recaptcha/api/siteverify",
    "hcaptcha": "https://api.hcaptcha.com/siteverify",
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
}


class CaptchaVerifyRequest(BaseModel):
    provider: str
    token: str
    site_key: str | None = None
    remote_ip: str | None = None


class CaptchaResult(BaseModel):
    provider: str
    token: str | None = None
    score: float | None = None
    success: bool
    challenge_ts: str | None = None
    hostname: str | None = None
    error_codes: list[str] = []


def _get_secret(provider: str) -> str:
    if provider in ("recaptcha_v2", "recaptcha_v3"):
        return RECAPTCHA_SECRET
    if provider == "hcaptcha":
        return HCAPTCHA_SECRET
    if provider == "turnstile":
        return TURNSTILE_SECRET
    return ""


@router.post("/verify", response_model=CaptchaResult)
async def verify_captcha(body: CaptchaVerifyRequest):
    """Verify a CAPTCHA token server-side and return the result."""
    secret = _get_secret(body.provider)
    if not secret:
        return CaptchaResult(
            provider=body.provider,
            success=False,
            error_codes=[f"no_secret_configured_for_{body.provider}"],
        )

    verify_url = VERIFY_URLS.get(body.provider)
    if not verify_url:
        raise HTTPException(400, f"Unsupported CAPTCHA provider: {body.provider}")

    form_data: dict[str, str] = {"secret": secret, "response": body.token}
    if body.remote_ip:
        form_data["remoteip"] = body.remote_ip
    if body.site_key and body.provider == "hcaptcha":
        form_data["sitekey"] = body.site_key

    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            r = await http.post(verify_url, data=form_data)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("CAPTCHA verification failed for %s: %s", body.provider, e)
        return CaptchaResult(
            provider=body.provider,
            success=False,
            error_codes=["verification_request_failed"],
        )

    return CaptchaResult(
        provider=body.provider,
        token=body.token[:20] + "...",
        score=data.get("score"),
        success=data.get("success", False),
        challenge_ts=data.get("challenge_ts"),
        hostname=data.get("hostname"),
        error_codes=data.get("error-codes", []),
    )
