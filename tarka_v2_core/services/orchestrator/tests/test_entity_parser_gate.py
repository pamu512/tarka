"""
Gate: ``entity_parser`` extracts strict ``ORD-########`` and related entities from chargeback-style email text.

Run::

    pytest tarka_v2_core/services/orchestrator/tests/test_entity_parser_gate.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


CHARGEBACK_EMAIL_SAMPLE = """
Subject: Chargeback opened — reason: merchandise not received

Hello,

The card network notified us of dispute CB-2025-4412 tied to marketplace order
ORD-10024567 (transaction cleared 2025-04-12). The cardholder lists
buyer.disputes@issuerbank.example as their contact, and copied our team at
ops-alerts+fraud@merchant.example.com.

The fulfillment record shows carrier UPS tracking 1Z999AA10123456784 signed
on 2025-04-09. USPS international acceptance scan 92612901001234567890123456
is also on file for the return label.

Please preserve evidence for ORD-10024567 — duplicate lines appear in threads.

Thanks,
Chargeback Operations
"""


def test_chargeback_email_extracts_expected_order_id() -> None:
    from orchestrator.utils.entity_parser import parse_entities

    out = parse_entities(CHARGEBACK_EMAIL_SAMPLE)

    assert out.order_ids == ("ORD-10024567",), "deduped single strict ORD-######## token"
    assert "ORD-10024567" in CHARGEBACK_EMAIL_SAMPLE
    assert "buyer.disputes@issuerbank.example" in out.emails
    assert "ops-alerts+fraud@merchant.example.com" in out.emails
    assert "1Z999AA10123456784" in out.tracking_numbers
    assert any(t.startswith("92612901001234567890123456") for t in out.tracking_numbers)


def test_strict_ord_pattern_only() -> None:
    from orchestrator.utils.entity_parser import parse_entities

    text = "ord-00000000 ORD-12345678 ORD12345678 Order ORD-87654321 done"
    out = parse_entities(text)
    assert out.order_ids == ("ORD-12345678", "ORD-87654321")


def test_empty_text() -> None:
    from orchestrator.utils.entity_parser import parse_entities

    assert parse_entities("") == parse_entities("   ")
