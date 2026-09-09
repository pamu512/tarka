"""D10.2 sample consumer: backup sink for tarka.pack_promote_export/v1."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from decision_api import promote_gitops
from decision_api.promote_gitops import emit_promote_export

REPO = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pack_promote_export_consumer as consumer  # noqa: E402

INCUMBENT_RE = re.compile(r"\b(Sift|Forter|Riskified|Feedzai|Featurespace|Unit21)\b")
EXAMPLE = REPO / "docs/examples/pack-promote-export-consumer.md"


def _emit(tmp_path, monkeypatch, **overrides):
    dest = tmp_path / "promote_export.jsonl"
    monkeypatch.setenv("PACK_GITOPS_EXPORT_PATH", str(dest))
    params = {
        "pack_id": "pack-a",
        "pack_hash": "abc",
        "mode": "active",
        "actor": "analyst",
        "reason": "human-promote",
        "file": "pack-a.json",
    }
    params.update(overrides)
    return emit_promote_export(**params), dest


def test_valid_export_event_writes_commit_stub(tmp_path, monkeypatch) -> None:
    event, _export = _emit(tmp_path, monkeypatch)
    dest = tmp_path / "stubs"
    result = consumer.consume_event(event, dest)
    assert result["ok"] is True
    path = Path(result["artifact"])
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert event["pack_id"] in text
    assert event["pack_hash"] in text
    assert event["emitted_at"] in text
    assert event["actor"] in text
    assert event["reason"] in text
    assert "backup" in text.lower()
    assert result["idempotency_key"] == (
        event["pack_id"],
        event["pack_hash"],
        event["emitted_at"],
    )


def test_duplicate_event_idempotent_no_double_write(tmp_path, monkeypatch) -> None:
    event, _export = _emit(tmp_path, monkeypatch)
    dest = tmp_path / "stubs"
    first = consumer.consume_event(event, dest)
    path = Path(first["artifact"])
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "\nKEEP\n", encoding="utf-8")
    second = consumer.consume_event(event, dest)
    assert second["ok"] is True
    assert second["idempotent"] is True
    assert Path(second["artifact"]) == path
    assert path.read_text(encoding="utf-8") == original + "\nKEEP\n"
    assert len(list(dest.glob("*.commit.txt"))) == 1


def test_malformed_event_structured_error_does_not_demote(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []

    def _mark(name: str):
        def _inner(*_a, **_k):
            calls.append(name)
            raise AssertionError(f"must not call {name}")

        return _inner

    monkeypatch.setattr("decision_api.l2_draft.propose_demote", _mark("propose_demote"))
    monkeypatch.setattr("decision_api.l2_draft.confirm_demote", _mark("confirm_demote"))
    monkeypatch.setattr(
        "decision_api.promote_gitops.emit_promote_export", _mark("emit_promote_export")
    )

    with pytest.raises(consumer.ConsumeError) as ei:
        consumer.consume_event('{"schema_id":"nope"}', tmp_path / "stubs")
    body = ei.value.as_dict()
    assert body["ok"] is False
    assert body["error"] == "malformed"
    assert "schema_id" in body["message"]
    assert calls == []
    assert list((tmp_path / "stubs").glob("*")) == []
    src = Path(consumer.__file__).read_text(encoding="utf-8")
    assert "propose_demote" not in src
    assert "confirm_demote" not in src


def test_emit_succeeds_when_consumer_disabled_or_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PACK_PROMOTE_EXPORT_CONSUMER_URL", "")
    event, export = _emit(tmp_path, monkeypatch)
    assert export.is_file()
    stored = json.loads(export.read_text(encoding="utf-8").strip())
    assert stored == event

    skipped = consumer.consume_after_emit(event, tmp_path / "stubs", notify_url="")
    assert skipped["skipped"] is True
    assert skipped["reason"] == "empty_url"
    assert (
        not (tmp_path / "stubs").exists() or list((tmp_path / "stubs").iterdir()) == []
    )

    def _boom(*_a, **_k):
        raise OSError("sink down")

    follow = consumer.consume_after_emit(
        event,
        tmp_path / "stubs-fail",
        notify_url="http://example.invalid/sink",
        notify=_boom,
    )
    assert follow.get("ok") is not True or follow.get("notified") is False
    assert export.is_file()
    assert json.loads(export.read_text(encoding="utf-8").strip()) == event
    src = Path(promote_gitops.__file__).read_text(encoding="utf-8")
    assert "consume_event" not in src
    assert "consume_after_emit" not in src
    assert "pack_promote_export_consumer" not in src


def test_example_doc_honesty() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "tarka.pack_promote_export/v1" in text
    assert "backup" in lowered
    assert "desk promote" in lowered
    assert "gitlab-grade" not in lowered
    assert "git required to promote" not in lowered
    assert "open-source" not in lowered
    assert "open source" not in lowered
    assert " oss" not in lowered and not lowered.startswith("oss")
    assert INCUMBENT_RE.search(text) is None
    assert "scripts/pack_promote_export_consumer.py" in text
