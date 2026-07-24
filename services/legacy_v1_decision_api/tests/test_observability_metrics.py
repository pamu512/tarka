"""Shared observability Metrics (R1.4): path + safe tenant_query + 4xx/5xx."""

from observability import Metrics


def test_http_requests_total_includes_tenant_query_label():
    m = Metrics("unit-test")
    m.record_request("GET", "/v1/audit/{trace_id}", 200, 0.01, tenant_query_scope="present")
    m.record_request("GET", "/v1/health", 200, 0.02, tenant_query_scope="absent")
    text = m.to_prometheus()
    assert 'tenant_query="present"' in text
    assert 'tenant_query="absent"' in text
    assert "http_requests_total{" in text


def test_client_and_server_error_counters():
    m = Metrics("unit-test")
    m.record_request("GET", "/v1/x", 404, 0.01, tenant_query_scope="absent")
    m.record_request("POST", "/v1/y", 500, 0.02, tenant_query_scope="present")
    text = m.to_prometheus()
    assert "http_client_errors_total{" in text
    assert "http_server_errors_total{" in text
    summary = m.request_count_summary()
    assert summary["http_client_errors_total_observed"] == 1
    assert summary["http_server_errors_total_observed"] == 1


def test_request_count_summary_includes_4xx_total():
    m = Metrics("unit-test")
    m.record_request("GET", "/z", 200, 0.001, tenant_query_scope="absent")
    s = m.request_count_summary()
    assert "http_client_errors_total_observed" in s
    assert s["http_client_errors_total_observed"] == 0
