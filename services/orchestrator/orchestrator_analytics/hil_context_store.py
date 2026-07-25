"""ClickHouse-backed store for ``tarka_analytics.hil_context_overrides``."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from orchestrator_analytics.cloud_provider import _try_connect_clickhouse

logger = logging.getLogger(__name__)

HIL_OVERRIDES_TABLE = "tarka_analytics.hil_context_overrides"


class HilOverrideType(str, Enum):
    ALLOW_SEASONAL_SPIKE = "ALLOW_SEASONAL_SPIKE"
    FORCE_BLOCK = "FORCE_BLOCK"
    TEMPORARY_BASELINE_SHIFT = "TEMPORARY_BASELINE_SHIFT"


class HilContextStoreError(RuntimeError):
    """Base error for HIL override persistence."""


class HilContextStoreUnavailable(HilContextStoreError):
    """Raised when ClickHouse is required but not configured."""


class HilContextOverrideStore(Protocol):
    def insert_override(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        override_type: HilOverrideType,
        scope_key: str,
        expires_at: datetime,
        analyst_rationale: str,
    ) -> None: ...

    def list_active_overrides(
        self,
        *,
        tenant_id: str,
        entity_id: str,
    ) -> list[dict[str, Any]]: ...


def _parse_override_type(raw: Any) -> HilOverrideType:
    text = str(raw or "").strip()
    if text.isdigit():
        mapping = {
            "1": HilOverrideType.ALLOW_SEASONAL_SPIKE,
            "2": HilOverrideType.FORCE_BLOCK,
            "3": HilOverrideType.TEMPORARY_BASELINE_SHIFT,
        }
        if text in mapping:
            return mapping[text]
    return HilOverrideType(text)


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class ClickHouseHilContextOverrideStore:
    """Production store using ``clickhouse-connect`` (optional ``[cloud]`` extra)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def insert_override(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        override_type: HilOverrideType,
        scope_key: str,
        expires_at: datetime,
        analyst_rationale: str,
    ) -> None:
        sql = f"""
        INSERT INTO {HIL_OVERRIDES_TABLE} (
            tenant_id, entity_id, override_type, scope_key, expires_at, analyst_rationale
        ) VALUES (
            {{tenant_id:String}}, {{entity_id:String}}, {{override_type:String}},
            {{scope_key:String}}, {{expires_at:DateTime}}, {{analyst_rationale:String}}
        )
        """
        expiry = expires_at.astimezone(UTC).replace(tzinfo=None)
        try:
            self._client.query(
                sql,
                parameters={
                    "tenant_id": tenant_id.strip(),
                    "entity_id": entity_id.strip(),
                    "override_type": override_type.value,
                    "scope_key": scope_key.strip(),
                    "expires_at": expiry,
                    "analyst_rationale": analyst_rationale.strip(),
                },
            )
        except Exception as exc:
            raise HilContextStoreError(f"hil override insert failed: {exc}") from exc

    def list_active_overrides(
        self,
        *,
        tenant_id: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        sql = f"""
        SELECT
            override_type,
            scope_key,
            expires_at,
            created_at,
            analyst_rationale
        FROM {HIL_OVERRIDES_TABLE} FINAL
        WHERE tenant_id = {{tenant_id:String}}
          AND entity_id = {{entity_id:String}}
          AND expires_at > now()
        ORDER BY created_at DESC
        """
        try:
            result = self._client.query(
                sql,
                parameters={"tenant_id": tenant_id.strip(), "entity_id": entity_id.strip()},
            )
        except Exception as exc:
            raise HilContextStoreError(f"hil override fetch failed: {exc}") from exc

        rows: list[dict[str, Any]] = []
        for row in result.result_rows or ():
            override_raw, scope_key, expires_at, created_at, rationale = row
            otype = _parse_override_type(override_raw)
            rows.append(
                {
                    "override_type": otype.value,
                    "scope_key": str(scope_key or ""),
                    "expires_at": _coerce_datetime(expires_at).isoformat(),
                    "created_at": (
                        _coerce_datetime(created_at).isoformat() if created_at is not None else None
                    ),
                    "analyst_rationale": str(rationale or ""),
                },
            )
        return rows


class InMemoryHilContextOverrideStore:
    """Test double — no ClickHouse required."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def insert_override(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        override_type: HilOverrideType,
        scope_key: str,
        expires_at: datetime,
        analyst_rationale: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        self._rows.append(
            {
                "tenant_id": tenant_id.strip(),
                "entity_id": entity_id.strip(),
                "override_type": override_type.value,
                "scope_key": scope_key.strip(),
                "expires_at": expires_at.astimezone(UTC),
                "created_at": now,
                "analyst_rationale": analyst_rationale.strip(),
            },
        )

    def list_active_overrides(
        self,
        *,
        tenant_id: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        now = datetime.now(tz=UTC)
        tenant = tenant_id.strip()
        entity = entity_id.strip()
        out: list[dict[str, Any]] = []
        for row in self._rows:
            if row["tenant_id"] != tenant or row["entity_id"] != entity:
                continue
            expires = row["expires_at"]
            if isinstance(expires, datetime) and expires <= now:
                continue
            created = row.get("created_at")
            out.append(
                {
                    "override_type": row["override_type"],
                    "scope_key": row["scope_key"],
                    "expires_at": (
                        expires.isoformat() if isinstance(expires, datetime) else str(expires)
                    ),
                    "created_at": created.isoformat() if isinstance(created, datetime) else None,
                    "analyst_rationale": row["analyst_rationale"],
                },
            )
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out


def build_hil_context_override_store(
    *,
    client_override: Any | None = None,
) -> HilContextOverrideStore | None:
    client = client_override if client_override is not None else _try_connect_clickhouse()
    if client is None:
        return None
    return ClickHouseHilContextOverrideStore(client)
