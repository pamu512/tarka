from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from decision_api.config import settings
from decision_api.schemas import EvaluateRequest

"""External connector framework for third-party risk signals (Scameter first)."""


@dataclass(slots=True)
class ExternalSignalResult:
    provider_id: str
    score_delta: float = 0.0
    risk_score: float = 0.0
    tags: list[str] | None = None
    enrichments: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class ExternalSignalProvider(Protocol):
    provider_id: str

    async def evaluate(
        self,
        http: httpx.AsyncClient,
        body: EvaluateRequest,
        features: dict[str, Any],
    ) -> ExternalSignalResult | None: ...


def _bounded_score_delta(value: float) -> float:
    return max(0.0, min(20.0, float(value)))


def _risk_score_to_delta(risk_score_0_100: float) -> float:
    score = max(0.0, min(100.0, float(risk_score_0_100)))
    return round((score / 100.0) * 12.0, 4)


class ScameterSignalProvider:
    provider_id = "scameter"

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = max(0.2, float(timeout_seconds))

    async def evaluate(
        self,
        http: httpx.AsyncClient,
        body: EvaluateRequest,
        features: dict[str, Any],
    ) -> ExternalSignalResult | None:
        if not self.base_url:
            return None

        payload: dict[str, Any] = {
            "tenant_id": body.tenant_id,
            "entity_id": body.entity_id,
            "event_type": body.event_type.value,
            "session_id": body.session_id,
            "context": {
                "phone": body.payload.get("phone"),
                "account": body.payload.get("account_id") or body.entity_id,
                "url": body.payload.get("url"),
                "ip": features.get("ip_address") or body.payload.get("ip_address"),
            },
        }
        headers: dict[str, str] = {}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        resp = await http.post(
            f"{self.base_url}/v1/risk/lookup",
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None

        risk_score = data.get("risk_score")
        try:
            rs = max(0.0, min(100.0, float(risk_score)))
        except (TypeError, ValueError):
            rs = 0.0
        delta = _risk_score_to_delta(rs)

        tags = []
        if rs >= 70:
            tags.append("scameter_high_risk")
        elif rs >= 40:
            tags.append("scameter_medium_risk")
        tags.extend([f"scameter:{str(x).strip()}" for x in (data.get("signals") or []) if str(x).strip()])

        enrichments = {
            "scameter_risk_score": rs,
            "scameter_confidence": data.get("confidence"),
            "scameter_version": data.get("model_version"),
        }
        return ExternalSignalResult(
            provider_id=self.provider_id,
            score_delta=delta,
            risk_score=rs,
            tags=tags,
            enrichments=enrichments,
            raw=data,
        )


def configured_external_signal_providers() -> list[ExternalSignalProvider]:
    providers: list[ExternalSignalProvider] = []
    if settings.scameter_enabled and settings.scameter_base_url.strip():
        providers.append(
            ScameterSignalProvider(
                base_url=settings.scameter_base_url.strip(),
                api_key=settings.scameter_api_key.strip(),
                timeout_seconds=settings.external_signal_timeout_seconds,
            )
        )
    return providers


async def evaluate_external_signals(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
) -> dict[str, Any] | None:
    providers = configured_external_signal_providers()
    if not providers:
        return None

    total_delta = 0.0
    max_risk = 0.0
    tags: list[str] = []
    provider_ids: list[str] = []
    enrichments: dict[str, Any] = {}
    provider_payloads: dict[str, Any] = {}
    for provider in providers:
        result = await provider.evaluate(http, body, features)
        if result is None:
            continue
        provider_ids.append(result.provider_id)
        total_delta += _bounded_score_delta(result.score_delta)
        max_risk = max(max_risk, max(0.0, min(100.0, float(result.risk_score))))
        tags.extend(result.tags or [])
        if isinstance(result.enrichments, dict):
            enrichments.update(result.enrichments)
        if isinstance(result.raw, dict):
            provider_payloads[result.provider_id] = result.raw

    if not provider_ids:
        return None

    return {
        "providers": provider_ids,
        "score_delta": round(_bounded_score_delta(total_delta), 4),
        "risk_score": round(max_risk, 4),
        "tags": list(dict.fromkeys(tags)),
        "enrichments": enrichments,
        "provider_payloads": provider_payloads,
    }
