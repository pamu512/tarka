"""Pydantic v2 models for Fingerprint Server API v3 envelopes and Tarka normalization.

References (public docs / OpenAPI excerpts):
- ``GET https://{region}.api.fpjs.io/events/{request_id}`` with ``Auth-API-Key``.
- Response root: ``{"products": { ... }}`` (``EventsGetResponse``).
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .exceptions import (
    FingerprintIdentificationFailedError,
    FingerprintRateLimitError,
)

# --- Vendor API error envelope (403/404 JSON) ---


class FingerprintApiErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class FingerprintApiErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: FingerprintApiErrorBody


# --- Identification (core product) ---


class Confidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: float = Field(..., ge=0.0, le=1.0)


class IdentificationData(BaseModel):
    """Subset of ``identification.data`` used for decisions; unknown fields preserved via extra."""

    model_config = ConfigDict(extra="allow")

    visitorId: str | None = None
    requestId: str | None = None
    linkedId: str | None = None
    incognito: bool | None = None
    ip: str | None = None
    visitorFound: bool | None = None
    replayed: bool | None = None
    confidence: Confidence | None = None


class IdentificationProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: IdentificationData | None = None
    error: FingerprintApiErrorBody | None = None


class BotResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    result: str | None = None
    type: str | None = None


class BotdData(BaseModel):
    model_config = ConfigDict(extra="allow")

    bot: BotResult | None = None


class BotdProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: BotdData | None = None
    error: FingerprintApiErrorBody | None = None


class BooleanSignalData(BaseModel):
    """Shared shape for many Smart Signals: ``{ "result": bool, ... }``."""

    model_config = ConfigDict(extra="allow")

    result: bool | None = None


class SmartSignalProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: BooleanSignalData | dict[str, Any] | None = None
    error: FingerprintApiErrorBody | None = None


class Products(BaseModel):
    """Typed slice of ``products``; additional product keys are ignored but available via model_dump if needed."""

    model_config = ConfigDict(extra="ignore")

    identification: IdentificationProduct | None = None
    botd: BotdProduct | None = None
    vpn: SmartSignalProduct | None = None
    proxy: SmartSignalProduct | None = None
    tor: SmartSignalProduct | None = None
    incognito: SmartSignalProduct | None = None
    tampering: SmartSignalProduct | None = None
    virtualMachine: SmartSignalProduct | None = None
    ipBlocklist: SmartSignalProduct | None = None
    emulator: SmartSignalProduct | None = None
    jailbroken: SmartSignalProduct | None = None
    rootApps: SmartSignalProduct | None = None


class EventsGetResponse(BaseModel):
    """Server API v3 successful JSON body for ``GET /events/{request_id}``."""

    model_config = ConfigDict(extra="forbid")

    products: Products


# --- Tarka unified outbound ---


class TarkaVendorProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: Literal["fingerprint"] = "fingerprint"
    request_id: str
    visitor_id: str | None = None
    region_base_url: str


class TarkaRiskSignal(BaseModel):
    """Single normalized signal for downstream rule engines."""

    model_config = ConfigDict(extra="forbid")

    score_0_100: float = Field(..., ge=0.0, le=100.0)
    reason_codes: list[str]
    vendor: Literal["fingerprint"] = "fingerprint"
    provenance: TarkaVendorProvenance
    features: dict[str, Any] = Field(default_factory=dict)


def _bool_result(data: BooleanSignalData | dict[str, Any] | None) -> bool | None:
    if data is None:
        return None
    if isinstance(data, dict):
        r = data.get("result")
        return bool(r) if isinstance(r, bool) else None
    return data.result


def _score_from_api_response(resp: EventsGetResponse, *, region_base_url: str) -> TarkaRiskSignal:
    ident = resp.products.identification
    if ident is None:
        raise ValueError("products.identification missing")
    if ident.error is not None:
        msg = ident.error.message
        code = ident.error.code
        if "429" in str(code) or "Too Many Requests" in str(code):
            raise FingerprintRateLimitError(msg, retry_after_seconds=None)
        raise FingerprintIdentificationFailedError(msg, fp_error_code=str(code))
    if ident.data is None:
        raise ValueError("products.identification.data missing")
    rid = ident.data.requestId
    if not rid:
        raise ValueError("products.identification.data.requestId missing")
    visitor = ident.data.visitorId

    reasons: list[str] = ["fingerprint:identification_ok"]
    score = 10.0
    if ident.data.confidence is not None:
        score = max(score, ident.data.confidence.score * 100.0)
        reasons.append("fingerprint:confidence")

    def bump(flag: bool | None, code: str, w: float) -> None:
        nonlocal score
        if flag is True:
            score += w
            reasons.append(code)

    bump(ident.data.incognito, "fingerprint:incognito", 12.0)

    botd = resp.products.botd
    if (
        botd
        and botd.error
        and ("429" in str(botd.error.code) or "TooManyRequests" in str(botd.error.code))
    ):
        raise FingerprintRateLimitError(botd.error.message, retry_after_seconds=None)
    bot_res = botd.data.bot.result if botd and botd.data and botd.data.bot else None
    if bot_res and bot_res not in ("notDetected", "good", "ok"):
        score += 35.0
        reasons.append("fingerprint:bot_suspect")

    for field, label, weight in (
        (resp.products.vpn, "fingerprint:vpn", 22.0),
        (resp.products.proxy, "fingerprint:proxy", 18.0),
        (resp.products.tor, "fingerprint:tor", 30.0),
        (resp.products.tampering, "fingerprint:tampering", 25.0),
        (resp.products.virtualMachine, "fingerprint:virtual_machine", 15.0),
        (resp.products.ipBlocklist, "fingerprint:ip_blocklist", 28.0),
        (resp.products.emulator, "fingerprint:emulator", 20.0),
        (resp.products.jailbroken, "fingerprint:jailbroken", 18.0),
        (resp.products.rootApps, "fingerprint:root_apps", 18.0),
    ):
        if (
            field
            and field.error
            and ("429" in str(field.error.code) or "TooManyRequests" in str(field.error.code))
        ):
            raise FingerprintRateLimitError(field.error.message, retry_after_seconds=None)
        br = _bool_result(field.data if field else None)  # type: ignore[arg-type]
        bump(br, label, weight)

    sig_inc = resp.products.incognito
    if sig_inc and sig_inc.data:
        bump(_bool_result(sig_inc.data), "fingerprint:smart_signal_incognito", 8.0)

    score = float(max(0.0, min(100.0, math.ceil(score))))

    features: dict[str, Any] = {
        "visitor_id": visitor,
        "visitor_found": ident.data.visitorFound,
        "replayed": ident.data.replayed,
        "ip": ident.data.ip,
        "linked_id": ident.data.linkedId,
    }

    return TarkaRiskSignal(
        score_0_100=score,
        reason_codes=reasons,
        provenance=TarkaVendorProvenance(
            request_id=rid,
            visitor_id=visitor,
            region_base_url=region_base_url,
        ),
        features=features,
    )


def fingerprint_events_response_to_tarka(
    resp: EventsGetResponse, *, region_base_url: str
) -> TarkaRiskSignal:
    """Map strict ``EventsGetResponse`` to ``TarkaRiskSignal``."""

    return _score_from_api_response(resp, region_base_url=region_base_url)


class WebhookEnvelope(BaseModel):
    """Webhook bodies mirror Server API responses (``products``) or legacy flat JSON."""

    model_config = ConfigDict(extra="allow")

    products: Products | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, dict) and "products" not in data and "requestId" in data:
            # Legacy / flat: wrap minimal identification for unified scoring path.
            rid = data.get("requestId")
            if not isinstance(rid, str) or not rid:
                return data
            wrapped = {
                "products": {
                    "identification": {
                        "data": {
                            k: data[k]
                            for k in (
                                "visitorId",
                                "requestId",
                                "linkedId",
                                "incognito",
                                "ip",
                                "visitorFound",
                                "replayed",
                                "confidence",
                            )
                            if k in data
                        }
                    }
                }
            }
            # carry over smart-signal keys that appear at root in legacy payloads
            for key in (
                "vpn",
                "proxy",
                "tor",
                "botd",
                "tampering",
                "incognito",
                "virtualMachine",
                "ipBlocklist",
                "emulator",
                "jailbroken",
                "rootApps",
            ):
                if key in data and key != "incognito":
                    wrapped["products"][key] = (
                        {"data": data[key]} if isinstance(data[key], dict) else data[key]
                    )
            return wrapped
        return data


def parse_webhook_payload(raw: dict[str, Any]) -> EventsGetResponse:
    """Parse webhook JSON dict into ``EventsGetResponse`` (supports wrapped legacy)."""

    env = WebhookEnvelope.model_validate(raw)
    if env.products is None:
        raise ValueError("webhook payload missing products after normalization")
    return EventsGetResponse(products=env.products)


def webhook_payload_to_tarka(raw: dict[str, Any], *, region_base_url: str) -> TarkaRiskSignal:
    """Convenience: dict → ``TarkaRiskSignal`` for HTTP handlers."""

    return fingerprint_events_response_to_tarka(
        parse_webhook_payload(raw), region_base_url=region_base_url
    )
