"""Evaluate copies graph relation-growth windows onto the feature map."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from circuit import CircuitOpenError
from decision_api.evaluate import enrichment
from decision_api.evaluate.enrichment import (
    attach_growth_to_features,
    fetch_relation_growth,
)


def test_attach_growth_writes_int_omits_null():
    feats: dict = {}
    attach_growth_to_features(
        feats,
        {
            "windows": [
                {"window": "1h", "count": 3, "threshold": 5},
                {"window": "24h", "count": None, "threshold": 15},
                {"window": "6h", "count": 0, "threshold": 8},
            ]
        },
    )
    assert feats["relation_growth_1h"] == 3
    assert "relation_growth_24h" not in feats
    assert feats["relation_growth_6h"] == 0


def test_attach_growth_noop_on_none():
    feats = {"event_count_1h": 1}
    attach_growth_to_features(feats, None)
    assert feats == {"event_count_1h": 1}


def test_attach_growth_noop_on_empty_or_non_dict():
    feats: dict = {}
    attach_growth_to_features(feats, {})
    attach_growth_to_features(feats, {"windows": "nope"})
    attach_growth_to_features(feats, {"windows": [{"window": "1h"}]})
    assert feats == {}


def _bind(*, circuit: Any | None = None) -> None:
    async def _pass(fn):
        return await fn()

    enrichment.bind_runtime(
        circuit_graph=circuit or SimpleNamespace(call=_pass),
        circuit_feature=object(),
        metrics_inc=lambda *_a, **_k: None,
        upstream_headers=lambda: {},
    )


class _CountingHttp:
    def __init__(
        self, body: dict[str, Any] | Exception, status_code: int = 200
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.body, Exception):
            raise self.body
        return httpx.Response(
            self.status_code,
            json=self.body,
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_growth_empty_url_omits_all_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "")
    http = _CountingHttp({"windows": [{"window": "1h", "count": 3}]})
    data = await fetch_relation_growth(http, "t1", "e1")  # type: ignore[arg-type]
    assert data is None
    assert http.calls == []
    feats: dict = {"event_count_1h": 1}
    attach_growth_to_features(feats, data)
    assert "relation_growth_1h" not in feats


@pytest.mark.asyncio
async def test_fetch_growth_graph_missing_omits_request(
    monkeypatch: pytest.MonkeyPatch,
):
    _bind()
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "http://graph.test")
    http = _CountingHttp({"windows": [{"window": "1h", "count": 3}]})
    tags = ["graph:missing"]
    data = await enrichment.fetch_relation_growth_wrapped(
        http,  # type: ignore[arg-type]
        "t1",
        "e1",
        tags,
        {},
    )
    assert data is None
    assert http.calls == []
    feats: dict = {}
    attach_growth_to_features(feats, data)
    assert feats == {}


@pytest.mark.asyncio
async def test_fetch_growth_disabled_omits_request(monkeypatch: pytest.MonkeyPatch):
    _bind()
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "http://graph.test")
    http = _CountingHttp({"windows": [{"window": "1h", "count": 3}]})
    tags: list[str] = []
    data = await enrichment.fetch_relation_growth_wrapped(
        http,  # type: ignore[arg-type]
        "t1",
        "e1",
        tags,
        {"disable_graph": True},
    )
    assert data is None
    assert http.calls == []


@pytest.mark.asyncio
async def test_fetch_growth_request_fail_omits_all_keys(
    monkeypatch: pytest.MonkeyPatch,
):
    _bind()
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "http://graph.test")
    http = _CountingHttp(httpx.HTTPError("boom"))
    tags: list[str] = []
    data = await enrichment.fetch_relation_growth_wrapped(
        http,  # type: ignore[arg-type]
        "t1",
        "e1",
        tags,
        {},
    )
    assert data is None
    feats: dict = {}
    attach_growth_to_features(feats, data)
    assert feats == {}
    assert "relation_growth_1h" not in feats


@pytest.mark.asyncio
async def test_fetch_growth_circuit_open_omits_all_keys(
    monkeypatch: pytest.MonkeyPatch,
):
    class _Open:
        async def call(self, fn):
            raise CircuitOpenError("graph")

    _bind(circuit=_Open())
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "http://graph.test")
    http = _CountingHttp({"windows": [{"window": "1h", "count": 3}]})
    tags: list[str] = []
    data = await enrichment.fetch_relation_growth_wrapped(
        http,  # type: ignore[arg-type]
        "t1",
        "e1",
        tags,
        {},
    )
    assert data is None
    assert http.calls == []
    attach_growth_to_features({}, data)


@pytest.mark.asyncio
async def test_fetch_growth_success_copies_int_omits_null(
    monkeypatch: pytest.MonkeyPatch,
):
    _bind()
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "http://graph.test")
    payload = {
        "entity_id": "e1",
        "tenant_id": "t1",
        "windows": [
            {"window": "1h", "count": 3, "threshold": 5},
            {"window": "24h", "count": None, "threshold": 15},
        ],
    }
    http = _CountingHttp(payload)
    data = await fetch_relation_growth(http, "t1", "e1")  # type: ignore[arg-type]
    assert data == payload
    assert len(http.calls) == 1
    assert http.calls[0]["url"] == "http://graph.test/v1/entities/e1/relation-growth"
    assert http.calls[0]["params"] == {"tenant_id": "t1"}
    feats: dict = {}
    attach_growth_to_features(feats, data)
    assert feats["relation_growth_1h"] == 3
    assert "relation_growth_24h" not in feats


def test_pipeline_attaches_growth_after_hop():
    src = (
        Path(enrichment.__file__)
        .resolve()
        .parents[0]
        .joinpath("pipeline.py")
        .read_text()
    )
    hop = src.index("attach_hop_to_features(features, graph_hop_v1)")
    fetch = src.index("fetch_relation_growth")
    attach = src.index("attach_growth_to_features(features")
    assert hop < fetch < attach


def test_evaluate_does_not_parse_graph_growth_windows():
    root = Path(enrichment.__file__).resolve().parents[0]
    for name in ("enrichment.py", "pipeline.py"):
        assert "GRAPH_GROWTH_WINDOWS" not in root.joinpath(name).read_text()
