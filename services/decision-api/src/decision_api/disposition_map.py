"""Buyer disposition_code → label_kind. Explicit label_kind wins."""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_DISPOSITION_MAP = {
    "confirmed_fraud": "fraud",
    "false_positive": "fp",
    "promo_abuse": "promo_abuse",
    "chargeback_lost": "chargeback",
    "collusion": "collusion",
}


class UnknownDisposition(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "unknown_disposition"
        super().__init__(f"unknown disposition_code: {code}")


def load_disposition_map() -> dict[str, str]:
    raw = (os.environ.get("QUEUE_DISPOSITION_MAP_JSON") or "").strip()
    if not raw:
        return dict(DEFAULT_DISPOSITION_MAP)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("QUEUE_DISPOSITION_MAP_JSON is not JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("QUEUE_DISPOSITION_MAP_JSON must be an object")
    out = dict(DEFAULT_DISPOSITION_MAP)
    for key, value in data.items():
        token = str(key or "").strip().lower()
        kind = str(value or "").strip().lower()
        if token and kind:
            out[token] = kind
    return out


def resolve_label_kind(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("label_kind") or "").strip()
    if explicit:
        return explicit
    code = str(payload.get("disposition_code") or "").strip().lower()
    if not code:
        return ""
    mapped = load_disposition_map().get(code)
    if mapped is None:
        raise UnknownDisposition(code)
    return mapped
