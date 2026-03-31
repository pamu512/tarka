"""Unit tests for integration-ingress enrichment — email, phone, IP analysis."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from integration_ingress.enrichment import (
    enrich_email,
    enrich_phone,
    enrich_ip,
    DISPOSABLE_DOMAINS,
    FREE_PROVIDERS,
    VOIP_PREFIXES,
)


# ---------- enrich_email ----------


class TestEnrichEmail:
    @pytest.mark.asyncio
    async def test_disposable_email_high_risk(self):
        http = AsyncMock()
        http.get = AsyncMock(side_effect=Exception("no network"))
        result = await enrich_email("user@tempmail.com", http)
        assert result["is_disposable"] is True
        assert result["risk_score"] >= 40

    @pytest.mark.asyncio
    async def test_free_provider_low_risk(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)

        result = await enrich_email("user@gmail.com", http)
        assert result["is_free_provider"] is True
        assert result["domain"] == "gmail.com"
        assert result["risk_score"] >= 5

    @pytest.mark.asyncio
    async def test_gravatar_exists_lowers_risk(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)

        result = await enrich_email("real@company.com", http)
        assert result["gravatar_exists"] is True
        no_gravatar_risk = result["risk_score"]

        mock_resp_404 = MagicMock()
        mock_resp_404.status_code = 404
        http.get = AsyncMock(return_value=mock_resp_404)

        result_no_grav = await enrich_email("real@company.com", http)
        assert result_no_grav["gravatar_exists"] is False
        assert result_no_grav["risk_score"] > no_gravatar_risk

    @pytest.mark.asyncio
    async def test_invalid_email_no_at_sign(self):
        http = AsyncMock()
        result = await enrich_email("notanemail", http)
        assert result["risk_score"] == 80

    @pytest.mark.asyncio
    async def test_empty_email(self):
        http = AsyncMock()
        result = await enrich_email("", http)
        assert result["risk_score"] == 80

    @pytest.mark.asyncio
    async def test_gravatar_network_error_handled(self):
        http = AsyncMock()
        http.get = AsyncMock(side_effect=Exception("timeout"))
        result = await enrich_email("user@example.com", http)
        assert result["gravatar_exists"] is False


# ---------- enrich_phone ----------


class TestEnrichPhone:
    @pytest.mark.asyncio
    async def test_valid_us_phone(self):
        result = await enrich_phone("+1-555-123-4567")
        assert result["is_valid_format"] is True
        assert result["country_code"] == "US"

    @pytest.mark.asyncio
    async def test_valid_uk_phone(self):
        result = await enrich_phone("+442071234567")
        assert result["is_valid_format"] is True
        assert result["country_code"] == "UK"

    @pytest.mark.asyncio
    async def test_valid_india_phone(self):
        result = await enrich_phone("+919876543210")
        assert result["is_valid_format"] is True
        assert result["country_code"] == "IN"

    @pytest.mark.asyncio
    async def test_short_phone_invalid(self):
        result = await enrich_phone("12345")
        assert result["is_valid_format"] is False
        assert result["risk_score"] >= 30

    @pytest.mark.asyncio
    async def test_voip_prefix_detected(self):
        result = await enrich_phone("+1-800-555-0100")
        assert result["is_voip_likely"] is True
        assert result["risk_score"] >= 15

    @pytest.mark.asyncio
    async def test_non_voip_phone(self):
        result = await enrich_phone("+1-212-555-0100")
        assert result["is_voip_likely"] is False


# ---------- enrich_ip ----------


class TestEnrichIp:
    @pytest.mark.asyncio
    async def test_successful_ip_enrichment(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "country": "United States",
            "city": "New York",
            "isp": "Verizon",
            "proxy": False,
            "hosting": False,
        }
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)

        result = await enrich_ip("8.8.8.8", http)
        assert result["country"] == "United States"
        assert result["isp"] == "Verizon"
        assert result["risk_score"] == 0

    @pytest.mark.asyncio
    async def test_proxy_ip_high_risk(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "country": "Germany",
            "city": "Frankfurt",
            "isp": "Datacenter GmbH",
            "proxy": True,
            "hosting": True,
        }
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)

        result = await enrich_ip("10.0.0.1", http)
        assert result["is_proxy"] is True
        assert result["is_hosting"] is True
        assert result["risk_score"] >= 45

    @pytest.mark.asyncio
    async def test_ip_api_failure_graceful(self):
        http = AsyncMock()
        http.get = AsyncMock(side_effect=Exception("timeout"))

        result = await enrich_ip("1.2.3.4", http)
        assert result["ip"] == "1.2.3.4"
        assert result["risk_score"] == 0
        assert result["country"] is None

    @pytest.mark.asyncio
    async def test_ip_api_non_200_handled(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)

        result = await enrich_ip("1.2.3.4", http)
        assert result["risk_score"] == 0

    @pytest.mark.asyncio
    async def test_ip_api_fail_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "fail", "message": "reserved range"}
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)

        result = await enrich_ip("192.168.1.1", http)
        assert result["country"] is None
