"""Second writer: sanctions match → AGE List hop without evaluate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from integration_ingress.sanctions import (
    maybe_ingest_list_hit,
    plan_list_hit_ingest,
    replay_journal_list_hits,
    verify_sanctions,
)


def test_plan_joins_person_to_list_not_a_merge():
    body = plan_list_hit_ingest(
        tenant_id="acme",
        subject_id="alice",
        list_id="NK-1",
    )
    assert body is not None
    assert body["source"] == "opensanctions"
    assert body["mapping"]["object_type"] == "List"
    assert body["mapping"]["relationship"] == "HAS_LIST"
    assert body["mapping"]["join_field"] == "entity_id"
    assert body["record"]["entity_id"] == "alice"
    assert body["record"]["list_id"] == "list:NK-1"
    other = plan_list_hit_ingest(tenant_id="acme", subject_id="bob", list_id="NK-1")
    assert other["record"]["entity_id"] == "bob"
    assert other["record"]["entity_id"] != body["record"]["entity_id"]


def test_plan_skips_synthetic_or_empty_join():
    assert plan_list_hit_ingest(tenant_id="acme", subject_id="", list_id="NK-1") is None
    assert plan_list_hit_ingest(tenant_id="acme", subject_id="  ", list_id="NK-1") is None
    assert plan_list_hit_ingest(tenant_id="acme", subject_id="alice", list_id="") is None
    assert (
        plan_list_hit_ingest(
            tenant_id="acme",
            subject_id="ops:acme:Alice",
            list_id="NK-1",
        )
        is None
    )
    assert (
        plan_list_hit_ingest(
            tenant_id="acme",
            subject_id="OPS:acme:Alice",
            list_id="NK-1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_maybe_ingest_posts_mapped_objects(monkeypatch):
    monkeypatch.setenv("GRAPH_SERVICE_URL", "http://graph.test")
    posted: list[tuple[str, dict]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        posted.append((str(request.url), json_loads(request.content)))
        return httpx.Response(200, json={"person_id": "alice", "object_id": "list:NK-1"})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        out = await maybe_ingest_list_hit(
            http,
            tenant_id="acme",
            subject_id="alice",
            list_id="NK-1",
        )
    assert out["status"] == "ok"
    assert posted[0][0].endswith("/v1/ingest/objects")
    assert posted[0][1]["record"]["entity_id"] == "alice"
    assert posted[0][1]["record"]["list_id"] == "list:NK-1"


def json_loads(raw: bytes) -> dict:
    import json

    return json.loads(raw.decode("utf-8"))


@pytest.mark.asyncio
async def test_maybe_ingest_empty_graph_url_is_unconfigured(monkeypatch):
    monkeypatch.delenv("GRAPH_SERVICE_URL", raising=False)
    async with httpx.AsyncClient() as http:
        out = await maybe_ingest_list_hit(
            http,
            tenant_id="acme",
            subject_id="alice",
            list_id="NK-1",
        )
    assert out["status"] == "graph:unconfigured"


@pytest.mark.asyncio
async def test_verify_sanctions_match_ingests_list(monkeypatch):
    monkeypatch.setenv("GRAPH_SERVICE_URL", "http://graph.test")
    ingest = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("integration_ingress.sanctions.maybe_ingest_list_hit", ingest)
    monkeypatch.setattr(
        "integration_ingress.sanctions._persist_screening_log",
        AsyncMock(return_value=__import__("uuid").uuid4()),
    )

    class _S:
        def dataset_cache_meta(self):
            return {}

        async def screen(self, name, country=None, dob=None):
            return [{"id": "NK-1", "score": 0.91, "matched_name": name.lower()}]

    monkeypatch.setattr("integration_ingress.sanctions._get_screener", lambda: _S())
    out = await verify_sanctions("acme", "alice", {"name": "Alice"})
    assert out["pep_sanctions_match"] is True
    ingest.assert_awaited_once()
    kwargs = ingest.await_args.kwargs
    assert kwargs["subject_id"] == "alice"
    assert kwargs["list_id"] == "NK-1"
    assert kwargs["tenant_id"] == "acme"


@pytest.mark.asyncio
async def test_verify_sanctions_miss_does_not_ingest(monkeypatch):
    ingest = AsyncMock()
    monkeypatch.setattr("integration_ingress.sanctions.maybe_ingest_list_hit", ingest)
    monkeypatch.setattr(
        "integration_ingress.sanctions._persist_screening_log",
        AsyncMock(return_value=__import__("uuid").uuid4()),
    )

    class _S:
        def dataset_cache_meta(self):
            return {}

        async def screen(self, name, country=None, dob=None):
            return []

    monkeypatch.setattr("integration_ingress.sanctions._get_screener", lambda: _S())
    out = await verify_sanctions("acme", "alice", {"name": "Nobody"})
    assert out["pep_sanctions_match"] is False
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_journal_ingests_hits_skips_synthetic(tmp_path, monkeypatch):
    journal = tmp_path / "j.jsonl"
    monkeypatch.setenv("SANCTIONS_SCREENING_JOURNAL_PATH", str(journal))
    from integration_ingress.sanctions import append_screening_journal

    append_screening_journal(
        {
            "schema_id": "tarka.sanctions_screening_journal/v1",
            "tenant_id": "acme",
            "subject_id": "alice",
            "match_found": True,
            "list_id": "NK-1",
        }
    )
    append_screening_journal(
        {
            "schema_id": "tarka.sanctions_screening_journal/v1",
            "tenant_id": "acme",
            "subject_id": "ops:acme:Bob",
            "match_found": True,
            "list_id": "NK-2",
        }
    )
    append_screening_journal(
        {
            "schema_id": "tarka.sanctions_screening_journal/v1",
            "tenant_id": "acme",
            "subject_id": "carol",
            "match_found": False,
            "list_id": "NK-3",
        }
    )
    ingest = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("integration_ingress.sanctions.maybe_ingest_list_hit", ingest)
    http = SimpleNamespace()
    out = await replay_journal_list_hits(http)
    assert out["ingested"] == 1
    assert out["skipped"] == 1
    ingest.assert_awaited_once()
    assert ingest.await_args.kwargs["subject_id"] == "alice"
    assert ingest.await_args.kwargs["list_id"] == "NK-1"


@pytest.mark.asyncio
async def test_replay_hits_survive_a_window_of_misses(tmp_path, monkeypatch):
    journal = tmp_path / "j.jsonl"
    monkeypatch.setenv("SANCTIONS_SCREENING_JOURNAL_PATH", str(journal))
    from integration_ingress.sanctions import append_screening_journal

    append_screening_journal(
        {
            "tenant_id": "acme",
            "subject_id": "alice",
            "match_found": True,
            "list_id": "NK-1",
        }
    )
    for i in range(500):
        append_screening_journal(
            {
                "tenant_id": "acme",
                "subject_id": f"miss-{i}",
                "match_found": False,
            }
        )
    ingest = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("integration_ingress.sanctions.maybe_ingest_list_hit", ingest)
    out = await replay_journal_list_hits(SimpleNamespace())
    assert out["ingested"] == 1
    ingest.assert_awaited_once()
    assert ingest.await_args.kwargs["subject_id"] == "alice"


@pytest.mark.asyncio
async def test_verify_sanctions_match_survives_ingest_failure(monkeypatch):
    ingest = AsyncMock(side_effect=RuntimeError("graph down"))
    monkeypatch.setattr("integration_ingress.sanctions.maybe_ingest_list_hit", ingest)
    monkeypatch.setattr(
        "integration_ingress.sanctions._persist_screening_log",
        AsyncMock(return_value=__import__("uuid").uuid4()),
    )

    class _S:
        def dataset_cache_meta(self):
            return {}

        async def screen(self, name, country=None, dob=None):
            return [{"id": "NK-1", "score": 0.91}]

    monkeypatch.setattr("integration_ingress.sanctions._get_screener", lambda: _S())
    out = await verify_sanctions("acme", "alice", {"name": "Alice"})
    assert out["pep_sanctions_match"] is True
    assert out["status"] == "verified"
    assert out["details"]["graph_ingest"]["status"] == "graph:write_failed"
