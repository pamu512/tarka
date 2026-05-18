"""Gate: document priming extracts order IDs from PDF/txt and builds the Shadow prompt."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.investigation_prime import (  # noqa: E402
    build_prime_prompt,
    extract_candidate_ids,
    prime_from_upload,
)
from orchestrator.main import create_app  # noqa: E402

_FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "order_prime.pdf"


def test_extract_ids_from_labeled_order_line() -> None:
    text = "Order ID: ORD-MOCK-GATE-01\nother noise"
    ids = extract_candidate_ids(text)
    assert "ORD-MOCK-GATE-01" in ids


def test_extract_ids_passport_label_and_token() -> None:
    text = "Passport no: AB1234567\nAlso PP-GATE-02 here"
    ids = extract_candidate_ids(text)
    assert "AB1234567" in ids
    assert "PP-GATE-02" in ids


def test_extract_ids_customer_cust_token() -> None:
    ids = extract_candidate_ids("Dispute linked to cust_99 and CUST-12 for review")
    assert "cust_99" in ids
    assert "CUST-12" in ids


def test_build_prime_prompt_multi() -> None:
    p = build_prime_prompt(["ORD-1", "550e8400-e29b-41d4-a716-446655440000"])
    assert "ORD-1" in p
    assert "550e8400-e29b-41d4-a716-446655440000" in p
    assert "cross-reference" in p.lower()


@pytest.mark.skipif(not _FIXTURE_PDF.is_file(), reason="order_prime.pdf fixture missing")
def test_prime_from_upload_pdf_fixture() -> None:
    data = _FIXTURE_PDF.read_bytes()
    ids, prompt = prime_from_upload(filename="order_prime.pdf", data=data)
    assert "ORD-MOCK-GATE-01" in ids
    assert "ORD-MOCK-GATE-01" in prompt
    assert prompt.startswith("I've detected IDs [")


def test_api_prime_pdf_fixture_gate() -> None:
    assert _FIXTURE_PDF.is_file()
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    with TestClient(app) as client:
        with _FIXTURE_PDF.open("rb") as fh:
            r = client.post(
                "/v1/investigation/prime",
                files={"file": ("order_prime.pdf", fh, "application/pdf")},
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "order_prime.pdf"
    assert "ORD-MOCK-GATE-01" in body["detected_ids"]
    assert "ORD-MOCK-GATE-01" in body["prime_prompt"]
    assert body["prime_prompt"].startswith("I've detected IDs [")
    assert isinstance(body.get("knowledge"), list)
    assert len(body["knowledge"]) >= 1


def test_api_prime_txt() -> None:
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    raw = b"Transaction ID: TXN-ABC-999\n"
    with TestClient(app) as client:
        r = client.post(
            "/v1/investigation/prime",
            files={"file": ("note.txt", raw, "text/plain")},
        )
    assert r.status_code == 200
    body = r.json()
    assert "TXN-ABC-999" in body["detected_ids"]
    assert isinstance(body.get("knowledge"), list)
