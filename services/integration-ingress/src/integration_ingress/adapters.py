from __future__ import annotations

"""KYC adapter registry. Adapters are registered by name.
Third-party adapters can be added by appending to ADAPTERS dict."""


from typing import Any, Awaitable, Callable

AdapterFn = Callable[[str, str, dict[str, Any] | None], Awaitable[dict[str, Any]]]


async def verify_mock(tenant_id: str, subject_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": "verified",
        "adapter": "mock",
        "subject_id": subject_id,
        "document_type": "passport",
        "liveness": "passed",
        "pep_sanctions_match": False,
        "confidence": 0.95,
        "raw_reference": "mock-ref",
        "details": raw or {},
    }


from integration_ingress.sanctions import verify_sanctions  # noqa: E402

# Global adapter registry
ADAPTERS: dict[str, AdapterFn] = {
    "mock": verify_mock,
    "sanctions": verify_sanctions,
}


def register_adapter(name: str, fn: AdapterFn) -> None:
    ADAPTERS[name] = fn


async def verify(adapter: str, tenant_id: str, subject_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    fn = ADAPTERS.get(adapter)
    if not fn:
        return {
            "status": "error",
            "adapter": adapter,
            "subject_id": subject_id,
            "document_type": None,
            "liveness": None,
            "pep_sanctions_match": None,
            "confidence": None,
            "raw_reference": None,
            "details": {"error": f"unknown adapter '{adapter}'; registered: {list(ADAPTERS.keys())}"},
        }
    return await fn(tenant_id, subject_id, raw)
