"""Gate: ``UnifiedSignalSchema`` aliases + inconsistent-signal validators."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402


def _base_payload(**overrides):
    base = {
        "ch": "a" * 64,
        "wv": "Apple GPU",
        "dm": 8,
        "ip": "203.0.113.10",
        "px": False,
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15",
        "sid": str(uuid4()),
        "ts": datetime.now(UTC).isoformat(),
        "sv": "1.0.0",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }
    base.update(overrides)
    return base


def test_gate_headless_with_mouse_velocity_raises() -> None:
    """Headless cannot report positive mouse velocity."""
    bad = _base_payload(hh=True, mv=12.5)
    with pytest.raises(ValidationError) as exc:
        UnifiedSignalSchema.model_validate(bad)
    errs = exc.value.errors()
    assert any(e.get("type") == "value_error" for e in errs)


def test_tampered_iphone4_ua_with_high_device_memory_raises() -> None:
    bad = _base_payload(
        ua="Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_0 like Mac OS X; en-us) AppleWebKit/532.9",
        dm=8,
    )
    with pytest.raises(ValidationError) as exc:
        UnifiedSignalSchema.model_validate(bad)
    msg = str(exc.value)
    assert "TAMPERED" in msg


def test_accepts_shorthand_aliases() -> None:
    m = UnifiedSignalSchema.model_validate(_base_payload())
    assert m.canvas_hash == "a" * 64
    assert m.device_memory == 8
    assert m.is_headless is False


def test_nonce_without_integrity_hash_rejected() -> None:
    bad = _base_payload()
    bad["n"] = "server-nonce-value"
    with pytest.raises(ValidationError) as exc:
        UnifiedSignalSchema.model_validate(bad)
    assert "session_nonce" in str(exc.value).lower() or "ih" in str(exc.value).lower()
