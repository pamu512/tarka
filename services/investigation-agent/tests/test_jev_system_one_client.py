"""S1: System One client timeout, auth, and schema checks. No retries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[2] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import httpx  # noqa: E402
import respx  # noqa: E402

from jev_system_one.client import (  # noqa: E402
    SystemOneClient,
    parse_systemone_response,
    systemone_endpoint,
)
from jev_system_one.questions import build_systemone_request

_FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "jev_system_one" / "fixtures"
_URL = "http://jev.test/v1/systemone"
_SECRET = "jev-secret-should-not-leak"


def _request() -> dict:
    return json.loads((_FIXTURES / "advise_sufficiency_v1.request.json").read_text(encoding="utf-8"))


def _response() -> dict:
    return json.loads((_FIXTURES / "advise_sufficiency_v1.response.json").read_text(encoding="utf-8"))


def test_golden_request_matches_builder() -> None:
    fixture = _request()
    assert build_systemone_request(fixture["evidence"]) == fixture
    assert systemone_endpoint("http://jev.test") == _URL
    assert systemone_endpoint(_URL) == _URL


def test_golden_response_parses_without_inventing_fields() -> None:
    parsed = parse_systemone_response(_response())
    assert parsed is not None
    assert parsed["has_enough_signal"] == {"value": True, "confidence": 0.71}
    assert parsed["review_priority"]["value"] == "routine"
    assert parsed["pattern_hint"]["value"] == "velocity"
    assert "prose" not in parsed


def test_yes_no_noul_normalizes_to_bool() -> None:
    body = _response()
    body["answers"]["has_enough_signal"]["value"] = "no"
    parsed = parse_systemone_response(body)
    assert parsed is not None
    assert parsed["has_enough_signal"]["value"] is False


def test_malformed_body_is_schema_failure() -> None:
    assert parse_systemone_response({"answers": {"has_enough_signal": {"value": "maybe"}}}) is None
    assert parse_systemone_response({"note": "free text"}) is None
    assert parse_systemone_response([]) is None


@respx.mock
async def test_success_sends_bearer_once_and_hides_key() -> None:
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_response()))
    client = SystemOneClient(base_url="http://jev.test", api_key=_SECRET, timeout_ms=400)
    judgment = await client.judge(_request())
    assert route.call_count == 1
    sent = route.calls[0].request
    assert sent.headers["authorization"] == f"Bearer {_SECRET}"
    assert judgment.error is None
    assert judgment.answers is not None
    assert _SECRET not in json.dumps(judgment.answers)
    assert _SECRET not in repr(judgment)


@respx.mock
async def test_empty_api_key_omits_authorization() -> None:
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_response()))
    client = SystemOneClient(base_url="http://jev.test", api_key="", timeout_ms=400)
    judgment = await client.judge(_request())
    assert judgment.error is None
    assert "authorization" not in route.calls[0].request.headers


async def _judge_once(route_result: httpx.Response | Exception) -> tuple[object, int]:
    if isinstance(route_result, Exception):
        route = respx.post(_URL).mock(side_effect=route_result)
    else:
        route = respx.post(_URL).mock(return_value=route_result)
    client = SystemOneClient(base_url="http://jev.test", api_key=_SECRET, timeout_ms=400)
    judgment = await client.judge(_request())
    return judgment, route.call_count


@respx.mock
async def test_timeout_is_error_without_retry_or_key_leak() -> None:
    judgment, calls = await _judge_once(httpx.TimeoutException("timed out"))
    assert judgment.error == "timeout"  # type: ignore[attr-defined]
    assert judgment.answers is None  # type: ignore[attr-defined]
    assert calls == 1
    assert _SECRET not in repr(judgment)


@respx.mock
async def test_http_5xx_is_error_without_retry_or_key_leak() -> None:
    judgment, calls = await _judge_once(httpx.Response(500, json={"error": _SECRET}))
    assert judgment.error == "http"  # type: ignore[attr-defined]
    assert judgment.answers is None  # type: ignore[attr-defined]
    assert calls == 1
    assert _SECRET not in repr(judgment)


@respx.mock
async def test_malformed_json_is_schema_failure() -> None:
    judgment, calls = await _judge_once(httpx.Response(200, content=b"not-json"))
    assert judgment.error == "schema"  # type: ignore[attr-defined]
    assert judgment.answers is None  # type: ignore[attr-defined]
    assert calls == 1


@respx.mock
async def test_malformed_answers_are_schema_failure() -> None:
    judgment, calls = await _judge_once(
        httpx.Response(200, json={"answers": {"has_enough_signal": {"value": "maybe"}}})
    )
    assert judgment.error == "schema"  # type: ignore[attr-defined]
    assert judgment.answers is None  # type: ignore[attr-defined]
    assert calls == 1


@respx.mock
async def test_redirect_is_not_followed() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(302, headers={"Location": "http://evil.test/v1/systemone"}))
    evil = respx.post("http://evil.test/v1/systemone").mock(return_value=httpx.Response(200, json=_response()))
    client = SystemOneClient(base_url="http://jev.test", api_key=_SECRET, timeout_ms=400)
    judgment = await client.judge(_request())
    assert judgment.error == "http"
    assert judgment.answers is None
    assert evil.call_count == 0


@respx.mock
async def test_transport_error_is_not_retried() -> None:
    route = respx.post(_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    client = SystemOneClient(base_url="http://jev.test", api_key=_SECRET, timeout_ms=400)
    judgment = await client.judge(_request())
    assert judgment.error == "transport"
    assert judgment.answers is None
    assert route.call_count == 1
    assert _SECRET not in repr(judgment)
