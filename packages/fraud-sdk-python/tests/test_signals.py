"""Unit tests for ServerSignalCollector."""

from fraud_stack_sdk.signals import ServerSignalCollector, _is_private_ip


class TestIsPrivateIp:
    def test_private_10(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_private_192(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_private_172(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_public(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_invalid(self):
        assert _is_private_ip("not-an-ip") is False

    def test_loopback(self):
        assert _is_private_ip("127.0.0.1") is True


class TestServerSignalCollector:
    def setup_method(self):
        self.collector = ServerSignalCollector()

    def test_basic_collect(self):
        signals = self.collector.collect(ip="8.8.8.8")
        assert signals["ip_address"] == "8.8.8.8"
        assert signals["is_bot"] is False
        assert signals["ip_is_datacenter"] is False

    def test_bot_ua(self):
        signals = self.collector.collect(
            ip="1.2.3.4",
            headers={"User-Agent": "Googlebot/2.1"},
        )
        assert signals["is_bot"] is True

    def test_curl_ua(self):
        signals = self.collector.collect(
            ip="1.2.3.4",
            headers={"user-agent": "curl/7.68.0"},
        )
        assert signals["is_bot"] is True

    def test_datacenter_asn(self):
        signals = self.collector.collect(ip="1.2.3.4", asn="AS14061")
        assert signals["ip_is_datacenter"] is True

    def test_unknown_asn(self):
        signals = self.collector.collect(ip="1.2.3.4", asn="AS9999")
        assert signals["ip_is_datacenter"] is False

    def test_proxy_headers_public_ip(self):
        signals = self.collector.collect(
            ip="8.8.8.8",
            headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8"},
        )
        assert signals["ip_is_proxy"] is True

    def test_proxy_headers_private_ip(self):
        signals = self.collector.collect(
            ip="10.0.0.1",
            headers={"x-forwarded-for": "10.0.0.2"},
        )
        assert signals["ip_is_proxy"] is False

    def test_country_passthrough(self):
        signals = self.collector.collect(ip="8.8.8.8", country="US")
        assert signals["ip_geo_country"] == "US"


class TestBuildDeviceContext:
    def setup_method(self):
        self.collector = ServerSignalCollector()

    def test_server_only(self):
        ctx = self.collector.build_device_context(ip="8.8.8.8", headers={"User-Agent": "Chrome/1"})
        assert ctx["platform"] == "server"
        assert ctx["device_id"]
        assert ctx["signals"]["ip_address"] == "8.8.8.8"
        assert ctx["attestation"] is None

    def test_merge_with_client(self):
        client_ctx = {
            "device_id": "client-device-123",
            "platform": "web",
            "signals": {"is_vpn": True, "canvas_fp_hash": "abc"},
        }
        ctx = self.collector.build_device_context(
            ip="1.2.3.4",
            headers={"User-Agent": "Mozilla/5.0"},
            client_device_context=client_ctx,
        )
        assert ctx["device_id"] == "client-device-123"
        assert ctx["platform"] == "web"
        assert ctx["signals"]["is_vpn"] is True
        assert ctx["signals"]["canvas_fp_hash"] == "abc"
        assert ctx["signals"]["ip_address"] == "1.2.3.4"
