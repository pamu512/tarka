"""Gate: GeoIP enrichment median latency < 1 ms per ``lookup`` / ``enrich_unified_signal``."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO = Path(__file__).resolve().parents[4]
for _p in (_SRC, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from signal_api.utils.geo_local import LocalGeoIpProvider, NullGeoEnrichmentProvider  # noqa: E402
from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402


def _sample_body() -> UnifiedSignalSchema:
    return UnifiedSignalSchema.model_validate(
        {
            "ch": "f" * 64,
            "wv": "x",
            "dm": 4,
            "ip": "8.8.8.8",
            "px": False,
            "ua": "Mozilla/5.0",
            "sid": "99999999-9999-9999-9999-999999999999",
            "ts": "2026-01-15T12:00:00+00:00",
            "sv": "96.0.0",
            "mv": 0.0,
            "tp": 0,
            "hh": False,
        },
    )


def test_null_provider_enrich_median_under_1ms() -> None:
    p = NullGeoEnrichmentProvider()
    body = _sample_body()
    n = 5_000
    samples_ns: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        _ = p.enrich_unified_signal(body)
        samples_ns.append(time.perf_counter_ns() - t0)
    med_ms = statistics.median(samples_ns) / 1_000_000.0
    assert med_ms < 1.0, f"median enrich latency {med_ms} ms (expected < 1 ms)"


def test_local_provider_lookup_median_under_1ms_with_mock_reader() -> None:
    """In-memory path: ``city()`` is sync; mock avoids shipping a real MMDB in CI."""

    class _Rec:
        def __init__(self) -> None:
            self.country = MagicMock(iso_code="US")
            self.city = MagicMock(name="Testville")

    reader = MagicMock()
    reader.city = MagicMock(return_value=_Rec())
    p = LocalGeoIpProvider(reader)
    n = 3_000
    samples_ns: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        _ = p.lookup("1.2.3.4")
        samples_ns.append(time.perf_counter_ns() - t0)
    med_ms = statistics.median(samples_ns) / 1_000_000.0
    assert med_ms < 1.0, f"median lookup latency {med_ms} ms (expected < 1 ms)"
    reader.city.assert_called()


@pytest.mark.parametrize("mmdb_env", ["SIGNAL_GEOIP_MMDB", "GEOIP_MMDB_PATH"])
def test_real_mmdb_optional_under_1ms_after_warmup(
    mmdb_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a real MMDB path is configured, warm up then assert median < 1 ms."""
    import os

    path = (os.environ.get("SIGNAL_GEOIP_MMDB") or os.environ.get("GEOIP_MMDB_PATH") or "").strip()
    if not path:
        pytest.skip(f"Set {mmdb_env} to a GeoLite2-City.mmdb for optional live MMDB gate")

    from pathlib import Path

    if not Path(path).is_file():
        pytest.skip(f"MMDB not found at {path}")

    monkeypatch.delenv("SIGNAL_GEOIP_MMDB", raising=False)
    monkeypatch.delenv("GEOIP_MMDB_PATH", raising=False)
    monkeypatch.setenv(mmdb_env, path)

    p = LocalGeoIpProvider.from_path(Path(path))
    if not isinstance(p, LocalGeoIpProvider):
        pytest.skip("geoip2 or MMDB load failed")

    for _ in range(5):
        p.lookup("8.8.8.8")

    n = 2_000
    samples_ns: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        _ = p.lookup("8.8.8.8")
        samples_ns.append(time.perf_counter_ns() - t0)
    p.close()

    med_ms = statistics.median(samples_ns) / 1_000_000.0
    assert med_ms < 1.0, f"median real MMDB lookup {med_ms} ms (expected < 1 ms)"
