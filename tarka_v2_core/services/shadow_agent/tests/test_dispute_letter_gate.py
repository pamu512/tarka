"""Gate (Prompt 126): ``generate_dispute_letter`` fills Markdown and embeds the cryptographic event hash."""

from __future__ import annotations

import pytest
from shadow_agent.agent import ShadowAgent
from shadow_agent.dispute_letter import (
    RepresentmentLetterIn,
    compute_cryptographic_event_hash,
    generate_dispute_letter,
)
from shadow_agent.main import build_app
from starlette.testclient import TestClient

_TEST_SHADOW_API_KEY = "shadow-sidecar-test-api-key"


class _NoopLlm:
    async def chat_json_validated(self, *args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("unused in representment route test")


def _auth_headers() -> dict[str, str]:
    return {"X-Shadow-Token": _TEST_SHADOW_API_KEY}


def test_generate_dispute_letter_embeds_expected_sha256() -> None:
    canonical = {
        "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "event": "card_not_present_capture",
        "amount": 129.99,
    }
    expected = compute_cryptographic_event_hash(canonical)
    assert len(expected) == 64

    ev = RepresentmentLetterIn(
        ip_address="198.51.100.77",
        device_hash="deadbeef" * 8,
        signature_evidence="3DS2 challenge OK; e-sign id ESIGN-4412",
        canonical_event=canonical,
        cryptographic_event_hash=expected,
    )
    out = generate_dispute_letter(ev)
    assert out.cryptographic_event_hash == expected
    assert f"`{expected}`" in out.letter_markdown
    assert "198.51.100.77" in out.letter_markdown
    assert "deadbeef" in out.letter_markdown
    assert "3DS2" in out.letter_markdown


def test_generate_dispute_letter_derives_hash_from_canonical_only() -> None:
    canonical = {"k": "v126"}
    expected = compute_cryptographic_event_hash(canonical)
    ev = RepresentmentLetterIn(
        ip_address="::1",
        device_hash="f" * 64,
        signature_evidence="Wet signature + DL match",
        canonical_event=canonical,
    )
    out = generate_dispute_letter(ev)
    assert out.cryptographic_event_hash == expected
    assert f"`{expected}`" in out.letter_markdown


def test_generate_dispute_letter_rejects_hash_canonical_mismatch() -> None:
    canonical = {"a": 1}
    good = compute_cryptographic_event_hash(canonical)
    bad = "0" * 64
    assert bad != good
    ev = RepresentmentLetterIn(
        ip_address="10.0.0.1",
        device_hash="ab" * 32,
        signature_evidence="wet ink signature on file",
        canonical_event=canonical,
        cryptographic_event_hash=bad,
    )
    with pytest.raises(ValueError, match="does not match"):
        generate_dispute_letter(ev)


def test_http_generate_dispute_letter_returns_letter_with_hash() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_NoopLlm()),  # type: ignore[arg-type]
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    canonical = {"order_id": "ORD-126", "ts": "2026-06-01T00:00:00Z"}
    h = compute_cryptographic_event_hash(canonical)
    body = {
        "ip_address": "203.0.113.9",
        "device_hash": "cafebabe" * 8,
        "signature_evidence": "Cardmember click-wrap + device binding",
        "canonical_event": canonical,
        "cryptographic_event_hash": h,
    }
    with TestClient(app) as client:
        r = client.post(
            "/v1/tools/generate-dispute-letter",
            json=body,
            headers=_auth_headers(),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cryptographic_event_hash"] == h
    assert h in data["letter_markdown"]
