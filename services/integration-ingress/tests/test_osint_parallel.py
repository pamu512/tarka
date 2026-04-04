"""Tests for unified OSINT path: parallel asyncio.gather and aggregation in full_osint_enrichment."""
from unittest.mock import AsyncMock, patch

import pytest

from integration_ingress.osint import OsintConfig, full_osint_enrichment


@pytest.mark.asyncio
async def test_full_osint_enrichment_requires_signal():
    cfg = OsintConfig()
    http = AsyncMock()
    out = await full_osint_enrichment(http=http, cfg=cfg)
    assert out.get("error")
    assert "required" in out["error"].lower()


@pytest.mark.asyncio
async def test_full_osint_enrichment_ip_only_parallel_branch():
    cfg = OsintConfig()
    http = AsyncMock()

    async def _fake_ip(*_a, **_kw):
        return {"aggregate_risk_score": 60.0, "sources": ["mock"]}

    with patch("integration_ingress.osint.enrich_ip_full", side_effect=_fake_ip):
        out = await full_osint_enrichment(ip="8.8.8.8", http=http, cfg=cfg)

    assert out["enrichments"]["ip"]["aggregate_risk_score"] == 60.0
    assert out["risk_level"] in ("low", "medium", "high", "critical")
    assert out["signals_queried"] >= 1
    assert "elapsed_ms" in out


@pytest.mark.asyncio
async def test_full_osint_enrichment_parallel_partial_failure_isolated():
    """One branch raises; others still contribute (return_exceptions=True semantics)."""
    cfg = OsintConfig()
    http = AsyncMock()

    async def _fail(*_a, **_kw):
        raise RuntimeError("upstream timeout")

    async def _ok(*_a, **_kw):
        return {"aggregate_risk_score": 25.0}

    with patch("integration_ingress.osint.enrich_ip_full", side_effect=_fail):
        with patch("integration_ingress.osint.enrich_email_full", side_effect=_ok):
            with patch("integration_ingress.osint.enrich_identity", side_effect=_ok):
                with patch("integration_ingress.osint.enrich_domain_full", side_effect=_ok):
                    out = await full_osint_enrichment(
                        ip="1.1.1.1",
                        email="user@company.com",
                        http=http,
                        cfg=cfg,
                    )

    assert "error" in out["enrichments"]["ip"]
    assert "email" in out["enrichments"]
    assert isinstance(out["composite_risk_score"], (int, float))
