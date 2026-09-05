"""Desk + AI author catalog: redis counters, graph growth keys, hops, payload extras.

One module imported by decision-api and shadow_agent. Decision-api does not parse
GRAPH_GROWTH_WINDOWS; growth rows are supplied by the graph-service policy GET.
"""

from __future__ import annotations

from typing import Any

from fraud_aggregates import (
    DEFAULT_FEATURE_OUTPUTS,
    _bundled_manifest_feature_outputs,
    valid_feature_output_rows,
)

CATALOG_HOPS = ("USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST")
PAYLOAD_FIELDS = (
    "amount",
    "currency",
    "device_type",
    "is_bot",
    "is_emulator",
    "is_rooted",
    "is_vpn",
    "session_duration",
    "country",
    "ip_is_proxy",
    "distinct_countries_7d",
    "email_domain",
)
LEGACY_ALIASES = (
    "tx_count_1h",
    "tx_count_24h",
    "tx_amount_1h",
    "tx_amount_24h",
    "distinct_devices_24h",
    "distinct_ips_24h",
)
IDENTITY_FIELDS = (
    "event_type",
    "entity_id",
    "session_id",
    "acc_id",
    "user_id",
    "device_fingerprint",
    "canvas_hash",
    "webgl_vendor",
    "user_agent",
    "screen_resolution",
    "timezone_offset",
    "language",
    "platform",
    "vendor",
    "vendor_fingerprint_score",
    "vendor_incognia_risk",
    "ip_address",
    "ip_risk_score",
    "geo_country",
    "geo_city",
    "amount",
    "currency",
)

_WINDOW_TOKENS = {
    300: "5m",
    3600: "1h",
    21600: "6h",
    86400: "24h",
    604800: "7d",
}


def window_token(window_seconds: int) -> str | None:
    """300→5m, 3600→1h, 21600→6h, 86400→24h, 604800→7d, else None."""
    try:
        return _WINDOW_TOKENS.get(int(window_seconds))
    except (TypeError, ValueError):
        return None


def _redis_rows() -> list[dict]:
    bundled = _bundled_manifest_feature_outputs()
    raw = list(bundled) if bundled is not None else None
    return valid_feature_output_rows(raw) or list(DEFAULT_FEATURE_OUTPUTS)


def _redis_entry(row: dict) -> dict[str, Any]:
    window_seconds = int(row["window_seconds"])
    entry: dict[str, Any] = {
        "name": str(row["name"]).strip(),
        "kind": row["kind"],
        "window_seconds": window_seconds,
    }
    token = window_token(window_seconds)
    if token is not None:
        entry["window"] = token
    field = row.get("field")
    if field:
        entry["field"] = field
    return entry


def _growth_entries(windows: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in windows:
        if not isinstance(w, dict):
            continue
        window = str(w.get("window") or "").strip()
        if not window:
            continue
        out.append(
            {
                "name": f"relation_growth_{window}",
                "kind": "growth",
                "window": window,
                "threshold": w.get("threshold"),
            }
        )
    return out


def build_author_catalog(*, graph_url: str, growth_windows: list[dict] | None) -> dict:
    """redis from valid feature_outputs; growth=[] if not graph_url or growth_windows is None."""
    growth: list[dict[str, Any]] = []
    if (graph_url or "").strip() and growth_windows is not None:
        growth = _growth_entries(growth_windows)
    return {
        "redis": [_redis_entry(r) for r in _redis_rows()],
        "growth": growth,
        "hops": [{"etype": e} for e in CATALOG_HOPS],
        "payload": [{"name": n} for n in PAYLOAD_FIELDS],
    }


def catalog_field_names(catalog: dict) -> frozenset[str]:
    """redis names + growth names + payload names."""
    names: set[str] = set()
    for key in ("redis", "growth", "payload"):
        for row in catalog.get(key) or []:
            if isinstance(row, dict) and row.get("name"):
                names.add(str(row["name"]))
    return frozenset(names)


def ai_allowed_fields(catalog: dict) -> frozenset[str]:
    """catalog_field_names | IDENTITY_FIELDS | LEGACY_ALIASES. No rate / baseline_ratio."""
    return catalog_field_names(catalog) | frozenset(IDENTITY_FIELDS) | frozenset(LEGACY_ALIASES)
