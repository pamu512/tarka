"""D9.1: bounded in-process webhook retry + dead-letter. emit_only stays default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    schedule_decision_outcomes,
)
from decision_api.enforcement import (
    apply_enforcement_adapters,
    enforcement_mode,
    read_enforcement_journal,
)

_REPO = Path(__file__).resolve().parents[3]
_CONTRACT = _REPO / "docs" / "contracts" / "enforcement-v1.md"
_CLAIM = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _journal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement_delivery.jsonl")
    )


def _emit_only(monkeypatch) -> None:
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)


async def _zero_wait(_attempt: int) -> None:
    return None


async def _apply(http, *, monkeypatch, tmp_path, url="http://hooks.test/enf", **kwargs):
    _emit_only(monkeypatch)
    _journal(tmp_path, monkeypatch)
    if url:
        monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", url)
    else:
        monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "decision_api.enforcement._retry_wait", _zero_wait, raising=False
    )
    defaults = dict(
        http=http,
        trace_id="tr-d91",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    defaults.update(kwargs)
    return await apply_enforcement_adapters(**defaults)


def test_default_enforcement_mode_stays_emit_only(monkeypatch) -> None:
    _emit_only(monkeypatch)
    assert enforcement_mode() == "emit_only"


@pytest.mark.asyncio
async def test_transient_5xx_retries_with_backoff_and_journals_each_attempt(
    monkeypatch, tmp_path
) -> None:
    from decision_api import enforcement as enf

    posts: list[int] = []
    waits: list[int] = []
    codes = [503, 503, 200]

    class _Http:
        async def post(self, *_a, **_k):
            posts.append(codes[len(posts)] if len(posts) < len(codes) else 200)
            return _Resp(posts[-1])

    async def _record_wait(attempt: int) -> None:
        waits.append(attempt)

    _emit_only(monkeypatch)
    _journal(tmp_path, monkeypatch)
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enf")
    monkeypatch.setattr(enf, "_retry_wait", _record_wait, raising=False)

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr-5xx",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    assert out["enforcement_mode"] == "emit_only"
    assert out["webhook"]["ok"] is True
    assert out["journal"]["status"] == "acked"
    assert posts == [503, 503, 200]
    assert waits == [1, 2]
    assert enf.ENFORCEMENT_RETRY_ATTEMPTS == 3
    assert enf.ENFORCEMENT_RETRY_BACKOFF_S == (0.05, 0.15)
    rows = read_enforcement_journal(10)
    statuses = [r["status"] for r in rows]
    assert statuses == ["retrying", "retrying", "acked"]
    assert [r.get("attempt_count") for r in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_exhausted_retries_dead_letter_does_not_raise(
    monkeypatch, tmp_path
) -> None:
    posts: list[int] = []

    class _Http:
        async def post(self, *_a, **_k):
            posts.append(503)
            return _Resp(503)

    out = await _apply(_Http(), monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert out["enforcement_mode"] == "emit_only"
    assert out["authority"] is False
    assert out["webhook"]["ok"] is False
    assert out["journal"]["status"] == "dead_lettered"
    assert posts == [503, 503, 503]
    rows = read_enforcement_journal(10)
    statuses = [r["status"] for r in rows]
    assert statuses.count("retrying") == 2
    dlq = [r for r in rows if r["status"] == "dead_lettered"]
    assert len(dlq) == 1
    assert dlq[0]["attempt_count"] == 3
    assert dlq[0].get("last_error") or dlq[0].get("http_status") == 503
    assert "demote" not in json.dumps(dlq[0]).lower()


@pytest.mark.asyncio
async def test_empty_webhook_url_skipped_no_retry_storm(monkeypatch, tmp_path) -> None:
    posts: list[int] = []

    class _Http:
        async def post(self, *_a, **_k):
            posts.append(1)
            raise AssertionError("empty URL must not POST")

    out = await _apply(_Http(), monkeypatch=monkeypatch, tmp_path=tmp_path, url="")
    assert out["webhook"] is None
    assert out["journal"]["status"] == "skipped"
    assert posts == []
    rows = read_enforcement_journal(10)
    assert rows[-1]["status"] == "skipped"
    assert rows[-1]["reason"] == "webhook_unset"
    assert all(r["status"] != "retrying" for r in rows)
    assert all(r["status"] != "dead_lettered" for r in rows)


@pytest.mark.asyncio
async def test_client_4xx_is_not_retried(monkeypatch, tmp_path) -> None:
    posts: list[int] = []

    class _Http:
        async def post(self, *_a, **_k):
            posts.append(404)
            return _Resp(404)

    out = await _apply(_Http(), monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert out["journal"]["status"] == "non_2xx"
    assert posts == [404]
    rows = read_enforcement_journal(10)
    assert [r["status"] for r in rows] == ["non_2xx"]


@pytest.mark.asyncio
async def test_transport_error_retries_then_dead_letters(monkeypatch, tmp_path) -> None:
    posts: list[int] = []

    class _Http:
        async def post(self, *_a, **_k):
            posts.append(1)
            raise TimeoutError("webhook timeout")

    out = await _apply(_Http(), monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert out["journal"]["status"] == "dead_lettered"
    assert posts == [1, 1, 1]
    dlq = [r for r in read_enforcement_journal(10) if r["status"] == "dead_lettered"]
    assert dlq[0]["attempt_count"] == 3
    assert "timeout" in str(dlq[0]["last_error"]).lower()


@pytest.mark.asyncio
async def test_emit_only_dlq_never_silent_block(monkeypatch, tmp_path) -> None:
    class _Http:
        async def post(self, *_a, **_k):
            return _Resp(502)

    out = await _apply(_Http(), monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert out["enforcement_mode"] == "emit_only"
    assert out["authority"] is False
    assert out["webhook_event"] == "decision.emitted"
    blob = json.dumps(out).lower()
    assert "silent block" not in blob
    assert "we blocked" not in blob
    assert out.get("evaluate_blocked") is None
    assert out.get("blocked") is not True


@pytest.mark.asyncio
async def test_handoff_only_when_contracted(monkeypatch, tmp_path) -> None:
    class _Http:
        async def post(self, *_a, **_k):
            return _Resp(204)

    _emit_only(monkeypatch)
    out = await _apply(_Http(), monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert out["enforcement_mode"] == "emit_only"
    assert out["authority"] is False

    monkeypatch.setenv("TARKA_ENFORCEMENT_MODE", "handoff")
    handed = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr-handoff",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    assert handed["enforcement_mode"] == "handoff"
    assert handed["authority"] is True
    assert handed["webhook_event"] == "decision.enforced"


def test_schedule_does_not_run_retry_loop_inline() -> None:
    ran = {"n": 0}

    class _Bg:
        def __init__(self) -> None:
            self.tasks: list[tuple] = []

        def add_task(self, fn, *args, **kwargs):
            self.tasks.append((fn, args, kwargs))

    async def _boom(*_a, **_k):
        ran["n"] += 1
        raise AssertionError("background fn must not run during schedule")

    bg = _Bg()
    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="t",
            tenant_id="ten",
            entity_id="e",
            event_type="payment",
            decision="deny",
            score=100.0,
            tags=["list:blacklist"],
            recommended_action=None,
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_boom,
        maybe_dispatch_challenge_webhook=_boom,
        broadcast_decision=_boom,
        publish_decision=_boom,
        metrics_inc=lambda *_a, **_k: None,
    )
    enf = [
        t
        for t in bg.tasks
        if getattr(t[0], "__name__", "") == "apply_enforcement_adapters"
        or getattr(getattr(t[0], "__wrapped__", None), "__name__", "")
        == "apply_enforcement_adapters"
        or "apply_enforcement_adapters" in getattr(t[0], "__qualname__", "")
        or "apply_enforcement_adapters" in getattr(t[0], "__name__", "")
    ]
    assert len(enf) == 1
    assert ran["n"] == 0


def test_contract_documents_retry_and_dlq() -> None:
    text = _CONTRACT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "dead_lettered" in lowered or "dead-letter" in lowered
    assert "retrying" in lowered
    assert "0.05" in text and "0.15" in text
    assert "background" in lowered or "fire-and-forget" in lowered
    assert "webhook_unset" in lowered
    assert "silent block" in lowered
    assert "d9.2" in lowered
    assert "celery" not in lowered or "do not" in lowered


def test_claim_lock_retry_dlq_both_sides() -> None:
    text = _CLAIM.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "dead-letter" in lowered or "dead_lettered" in lowered
    assert "bounded retry" in lowered or "in-process" in lowered
    assert "silent block" in lowered
    assert "demote" in lowered
    assert "redis" in lowered or "sqs" in lowered or "celery" in lowered
