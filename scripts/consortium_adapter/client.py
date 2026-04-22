from __future__ import annotations
import json
import os
from typing import Any
from urllib.parse import quote

import httpx

"""
HTTP client for Tarka Decision API consortium endpoints (`/v1/consortium/*`).

Use from Python or via `cli.py`. Requires matching `CONSORTIUM_SECRET` / Redis on the
server side; this adapter only speaks HTTP.
"""
__all__ = [
    "ConsortiumAdapter",
    "ingest_json_lines",
    "load_adapter_from_env",
    "validate_ingest_record",
]


def _path_segment(value: str) -> str:
    """Encode a path segment (tenant_id / entity_id may contain @, :, etc.)."""
    return quote(value, safe="")


class ConsortiumAdapter:
    """Sync client for consortium signal sharing, lookup, feedback, and tenant trust."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        """
        If ``http_client`` is set (e.g. tests with ``httpx.MockTransport``), it is used as-is
        and **not** closed by this adapter; ``base_url`` / ``api_key`` are ignored for construction.
        """
        self._owns_client = http_client is None
        if http_client is not None:
            self._client = http_client
            return
        self._base = base_url.rstrip("/")
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.Client(base_url=self._base, headers=headers, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ConsortiumAdapter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def share_signal(
        self,
        tenant_id: str,
        entity_id: str,
        signal_type: str,
        *,
        severity: float = 1.0,
        ttl_days: int = 30,
        consortium_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "signal_type": signal_type,
            "severity": severity,
            "ttl_days": ttl_days,
        }
        if consortium_id is not None:
            body["consortium_id"] = consortium_id
        r = self._client.post("/v1/consortium/share", json=body)
        r.raise_for_status()
        return r.json()

    def check_signal(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        consortium_id: str | None = None,
    ) -> dict[str, Any]:
        t = _path_segment(tenant_id)
        e = _path_segment(entity_id)
        params: dict[str, str] = {}
        if consortium_id is not None:
            params["consortium_id"] = consortium_id
        r = self._client.get(f"/v1/consortium/check/{t}/{e}", params=params or None)
        r.raise_for_status()
        return r.json()

    def post_feedback(
        self,
        tenant_id: str,
        entity_id: str,
        outcome: str,
        *,
        ttl_days: int = 30,
        consortium_id: str | None = None,
    ) -> dict[str, Any]:
        if outcome not in ("false_positive", "confirmed_fraud"):
            raise ValueError("outcome must be 'false_positive' or 'confirmed_fraud'")
        body: dict[str, Any] = {
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "outcome": outcome,
            "ttl_days": ttl_days,
        }
        if consortium_id is not None:
            body["consortium_id"] = consortium_id
        r = self._client.post("/v1/consortium/feedback", json=body)
        r.raise_for_status()
        return r.json()

    def set_tenant_trust(
        self,
        tenant_id: str,
        trust_score: float,
        *,
        consortium_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"tenant_id": tenant_id, "trust_score": trust_score}
        if consortium_id is not None:
            body["consortium_id"] = consortium_id
        r = self._client.post("/v1/consortium/trust", json=body)
        r.raise_for_status()
        return r.json()

    def ingest_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Dispatch a single normalized record (e.g. from JSON Lines).

        Required key: ``op`` ∈ share | check | feedback | trust.

        share: tenant_id, entity_id, signal_type; optional severity, ttl_days, consortium_id
        check: tenant_id, entity_id; optional consortium_id
        feedback: tenant_id, entity_id, outcome; optional ttl_days, consortium_id
        trust: tenant_id, trust_score; optional consortium_id
        """
        op = str(record.get("op", "")).strip().lower()
        cid = record.get("consortium_id")
        cid_opt = str(cid).strip() if cid is not None and str(cid).strip() else None

        if op == "share":
            return self.share_signal(
                str(record["tenant_id"]),
                str(record["entity_id"]),
                str(record["signal_type"]),
                severity=float(record.get("severity", 1.0)),
                ttl_days=int(record.get("ttl_days", 30)),
                consortium_id=cid_opt,
            )
        if op == "check":
            return self.check_signal(
                str(record["tenant_id"]),
                str(record["entity_id"]),
                consortium_id=cid_opt,
            )
        if op == "feedback":
            return self.post_feedback(
                str(record["tenant_id"]),
                str(record["entity_id"]),
                str(record["outcome"]),
                ttl_days=int(record.get("ttl_days", 30)),
                consortium_id=cid_opt,
            )
        if op == "trust":
            return self.set_tenant_trust(
                str(record["tenant_id"]),
                float(record["trust_score"]),
                consortium_id=cid_opt,
            )
        raise ValueError(f"unknown op: {op!r} (expected share|check|feedback|trust)")


def validate_ingest_record(record: dict[str, Any]) -> None:
    """Ensure ``record`` has ``op`` and required fields for that op (no HTTP)."""
    op = str(record.get("op", "")).strip().lower()
    if op == "share":
        for k in ("tenant_id", "entity_id", "signal_type"):
            if k not in record:
                raise KeyError(k)
        return
    if op == "check":
        for k in ("tenant_id", "entity_id"):
            if k not in record:
                raise KeyError(k)
        return
    if op == "feedback":
        for k in ("tenant_id", "entity_id", "outcome"):
            if k not in record:
                raise KeyError(k)
        if str(record["outcome"]) not in ("false_positive", "confirmed_fraud"):
            raise ValueError("outcome must be false_positive or confirmed_fraud")
        return
    if op == "trust":
        for k in ("tenant_id", "trust_score"):
            if k not in record:
                raise KeyError(k)
        return
    if not op:
        raise ValueError("missing op")
    raise ValueError(f"unknown op: {op!r}")


def ingest_json_lines(
    adapter: ConsortiumAdapter,
    text: str,
    *,
    dry_run: bool = False,
) -> tuple[int, int, list[str]]:
    """
    Parse JSON Lines (one JSON object per line; ``#`` starts a comment line).

    Returns (success_count, error_count, error_messages).
    """
    ok, err = 0, 0
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            rec = json.loads(raw)
            if not isinstance(rec, dict):
                raise TypeError("each line must be a JSON object")
            validate_ingest_record(rec)
            if not dry_run:
                adapter.ingest_record(rec)
            ok += 1
        except Exception as e:
            err += 1
            errors.append(f"line {lineno}: {e}")
    return ok, err, errors


def load_adapter_from_env() -> ConsortiumAdapter:
    """Build adapter from ``TARKA_DECISION_API_URL`` and optional ``TARKA_API_KEY``."""
    base = os.environ.get("TARKA_DECISION_API_URL", "http://127.0.0.1:8000").strip()
    key = os.environ.get("TARKA_API_KEY", "").strip() or None
    return ConsortiumAdapter(base, api_key=key)
