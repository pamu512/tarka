from __future__ import annotations
import json
import sys
from pathlib import Path

import httpx
import pytest

"""Tests for consortium_adapter HTTP client and ingest helpers."""
sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import (  # noqa: E402
    ConsortiumAdapter,
    ingest_json_lines,
    validate_ingest_record,
)


def test_validate_ingest_record_share_ok():
    validate_ingest_record(
        {"op": "share", "tenant_id": "t", "entity_id": "e", "signal_type": "ato"},
    )


def test_validate_ingest_record_unknown_op():
    with pytest.raises(ValueError, match="unknown op"):
        validate_ingest_record({"op": "nope", "tenant_id": "t"})


def test_validate_feedback_outcome():
    with pytest.raises(ValueError, match="outcome"):
        validate_ingest_record(
            {"op": "feedback", "tenant_id": "t", "entity_id": "e", "outcome": "bad"},
        )


def test_share_signal_request_body():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.method == "POST"
        body = json.loads(request.content.decode())
        assert body == {
            "tenant_id": "t1",
            "entity_id": "e1",
            "signal_type": "mule",
            "severity": 2.5,
            "ttl_days": 14,
            "consortium_id": "lane-a",
        }
        return httpx.Response(200, json={"signal_hash": "h", "consortium": {}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://example.test") as http:
        adapter = ConsortiumAdapter("http://ignored", http_client=http)
        try:
            adapter.share_signal(
                "t1",
                "e1",
                "mule",
                severity=2.5,
                ttl_days=14,
                consortium_id="lane-a",
            )
        finally:
            adapter.close()
    assert len(captured) == 1


def test_check_signal_encodes_path():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert "/v1/consortium/check/t%40x/e%2F1" in str(request.url) or request.url.path.endswith(
            "check/t%40x/e%2F1",
        )
        return httpx.Response(200, json={"enabled": True, "consortium": {}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://example.test") as http:
        adapter = ConsortiumAdapter("x", http_client=http)
        try:
            adapter.check_signal("t@x", "e/1")
        finally:
            adapter.close()


def test_ingest_json_lines_dry_run():
    adapter = ConsortiumAdapter("http://x", http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    try:
        ok, err, errors = ingest_json_lines(
            adapter,
            '{"op":"share","tenant_id":"a","entity_id":"b","signal_type":"x"}\n',
            dry_run=True,
        )
    finally:
        adapter.close()
    assert ok == 1 and err == 0 and errors == []


def test_ingest_json_lines_runs_share():
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://example.test") as http:
        adapter = ConsortiumAdapter("x", http_client=http)
        try:
            ok, err, _ = ingest_json_lines(
                adapter,
                '{"op":"share","tenant_id":"a","entity_id":"b","signal_type":"z"}\n',
                dry_run=False,
            )
        finally:
            adapter.close()
    assert ok == 1 and err == 0 and count == 1
