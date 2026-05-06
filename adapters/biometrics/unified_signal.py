"""Unified biometric vendor outputs for downstream rule engines.

Both Fingerprint and Incognia adapters expose a normalized signal shape with
``score_0_100``, ``reason_codes``, ``vendor``, ``provenance``, and ``features``.
This module provides a single discriminated union on ``vendor``.
"""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field, TypeAdapter

from adapters.biometrics.fingerprint.schemas import TarkaRiskSignal as FingerprintTarkaRiskSignal
from adapters.biometrics.incognia.schemas import IncogniaTarkaRiskSignal

BiometricTarkaRiskSignal = Annotated[
    Union[FingerprintTarkaRiskSignal, IncogniaTarkaRiskSignal],
    Field(discriminator="vendor"),
]

_biometric_adapter = TypeAdapter(BiometricTarkaRiskSignal)


def parse_biometric_tarka_signal(data: object) -> FingerprintTarkaRiskSignal | IncogniaTarkaRiskSignal:
    """Validate a dict or JSON-compatible structure into the correct vendor model."""

    return _biometric_adapter.validate_python(data)


def dump_biometric_tarka_signal(signal: FingerprintTarkaRiskSignal | IncogniaTarkaRiskSignal) -> dict:
    """Serialize a biometric signal to JSON-compatible dict."""

    return signal.model_dump(mode="json")
