"""HTTP loyalty warehouse pack fetch + validate (Track C contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from decision_api.loyalty_economics import evaluate_loyalty_economics

WAREHOUSE_SCHEMA_ID = "tarka.loyalty_warehouse_pack/v1"


class LoyaltyWarehouseError(ValueError):
    """Invalid or unreachable warehouse pack."""


def fetch_loyalty_warehouse_pack(
    url: str,
    *,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """GET JSON pack from ``url``. Raises LoyaltyWarehouseError on failure."""
    owns = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        try:
            resp = http.get(url)
        except httpx.HTTPError as exc:
            raise LoyaltyWarehouseError(f"warehouse fetch failed: {exc}") from exc
        if resp.status_code != 200:
            raise LoyaltyWarehouseError(f"warehouse HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise LoyaltyWarehouseError("warehouse response is not JSON") from exc
        if not isinstance(body, dict):
            raise LoyaltyWarehouseError("warehouse pack must be a JSON object")
        return validate_loyalty_warehouse_pack(body, now=now)
    finally:
        if owns:
            http.close()


def validate_loyalty_warehouse_pack(
    body: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate schema and hygiene; never claim eligible on incomplete feeds."""
    schema = str(body.get("schema_id") or "")
    if schema and schema != WAREHOUSE_SCHEMA_ID:
        raise LoyaltyWarehouseError(f"unexpected schema_id {schema!r}")
    entity_id = str(body.get("entity_id") or "").strip()
    if not entity_id:
        raise LoyaltyWarehouseError("entity_id required")
    snap = body.get("loyalty_feed_snapshot")
    cfg = body.get("loyalty_program_config")
    if not isinstance(snap, dict):
        raise LoyaltyWarehouseError("loyalty_feed_snapshot must be object")
    if not isinstance(cfg, dict):
        raise LoyaltyWarehouseError("loyalty_program_config must be object")

    gates = evaluate_loyalty_economics(
        entity_id=entity_id,
        feed_snapshot=snap,
        program_config=cfg,
        now=now,
    )
    status = str(gates.get("status") or "")
    if status in ("feeds_missing", "config_missing"):
        raise LoyaltyWarehouseError(f"warehouse pack not usable: status={status}")

    return {
        "schema_id": WAREHOUSE_SCHEMA_ID,
        "entity_id": entity_id,
        "as_of": body.get("as_of") or snap.get("as_of"),
        "loyalty_feed_snapshot": snap,
        "loyalty_program_config": cfg,
        "gates_preview": {
            "status": gates.get("status"),
            "order_eligible": (gates.get("gates") or {}).get("order", {}).get("eligible"),
            "order_decision_untouched": (gates.get("policy") or {}).get(
                "order_decision_untouched"
            ),
        },
    }
