"""Tests for :mod:`adapters.biometrics.unified_signal`."""

from __future__ import annotations

import unittest
from uuid import UUID

from adapters.biometrics.fingerprint.schemas import TarkaRiskSignal, TarkaVendorProvenance
from adapters.biometrics.incognia.schemas import IncogniaTarkaProvenance, IncogniaTarkaRiskSignal
from adapters.biometrics.unified_signal import dump_biometric_tarka_signal, parse_biometric_tarka_signal


class UnifiedSignalTests(unittest.TestCase):
    def test_parse_fingerprint_branch(self) -> None:
        raw = {
            "score_0_100": 42.0,
            "reason_codes": ["fingerprint:identification_ok"],
            "vendor": "fingerprint",
            "provenance": {
                "vendor": "fingerprint",
                "request_id": "req-1",
                "visitor_id": "v1",
                "region_base_url": "https://api.fpjs.io",
            },
            "features": {"k": 1},
        }
        m = parse_biometric_tarka_signal(raw)
        self.assertIsInstance(m, TarkaRiskSignal)
        self.assertEqual(m.vendor, "fingerprint")
        self.assertEqual(m.provenance.request_id, "req-1")

    def test_parse_incognia_branch(self) -> None:
        raw = {
            "score_0_100": 80.0,
            "reason_codes": ["incognia:code"],
            "vendor": "incognia",
            "provenance": {
                "vendor": "incognia",
                "assessment_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "api_base_url": "https://api.incognia.com",
            },
            "features": {},
        }
        m = parse_biometric_tarka_signal(raw)
        self.assertIsInstance(m, IncogniaTarkaRiskSignal)
        self.assertEqual(m.provenance.assessment_id, UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    def test_dump_round_trip(self) -> None:
        sig = IncogniaTarkaRiskSignal(
            score_0_100=10.0,
            reason_codes=["a"],
            provenance=IncogniaTarkaProvenance(
                assessment_id=UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff"),
                api_base_url="https://api.incognia.com",
            ),
        )
        d = dump_biometric_tarka_signal(sig)
        back = parse_biometric_tarka_signal(d)
        self.assertIsInstance(back, IncogniaTarkaRiskSignal)
        self.assertEqual(back.provenance.assessment_id, sig.provenance.assessment_id)


if __name__ == "__main__":
    unittest.main()
