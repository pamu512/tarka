"""tarka.pack_promote_export/v1 — emit payload lock + consumer contract fixture."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from decision_api.promote_gitops import SCHEMA_ID, emit_promote_export

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "docs/contracts/pack-promote-export-v1.md"

# Tip emit keys from emit_promote_export — do not invent extras.
REQUIRED_FIELDS = (
    "schema_id",
    "pack_id",
    "pack_hash",
    "mode",
    "actor",
    "reason",
    "file",
    "emitted_at",
)
INCUMBENT_RE = re.compile(r"\b(Sift|Forter|Riskified|Feedzai|Featurespace|Unit21)\b")


def test_schema_id_is_v1() -> None:
    assert SCHEMA_ID == "tarka.pack_promote_export/v1"


def test_emit_required_params_are_tip_fields_only() -> None:
    params = inspect.signature(emit_promote_export).parameters
    required = [n for n, p in params.items() if p.default is inspect.Parameter.empty]
    assert required == ["pack_id", "pack_hash", "mode", "actor", "reason"]
    assert "file" in params


def test_emit_payload_fields(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "promote_export.jsonl"
    monkeypatch.setenv("PACK_GITOPS_EXPORT_PATH", str(dest))
    event = emit_promote_export(
        pack_id="pack-a",
        pack_hash="abc",
        mode="active",
        actor="analyst",
        reason="human-promote",
        file="pack-a.json",
    )
    assert event["schema_id"] == SCHEMA_ID
    assert set(event) == set(REQUIRED_FIELDS)
    stored = json.loads(dest.read_text(encoding="utf-8").strip())
    assert stored == event
    assert stored["emitted_at"]


def test_write_failure_returns_event_no_raise(tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PACK_GITOPS_EXPORT_PATH", str(blocker / "out.jsonl"))
    event = emit_promote_export(
        pack_id="pack-a",
        pack_hash="abc",
        mode="active",
        actor="analyst",
        reason="human-promote",
    )
    assert event["schema_id"] == SCHEMA_ID
    assert set(event) == set(REQUIRED_FIELDS)


def test_contract_doc_matches_emit() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert SCHEMA_ID in text
    for field in REQUIRED_FIELDS:
        assert f"`{field}`" in text
    lowered = text.lower()
    assert "desk promote" in lowered
    assert "source of truth" in lowered or "sot" in lowered
    assert "backup" in lowered
    assert "append" in lowered
    assert "idempoten" in lowered
    assert "pack_id" in text and "pack_hash" in text and "emitted_at" in text


def test_contract_doc_non_goals_and_hygiene() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "not go-live" in lowered or "not the go-live" in lowered
    assert "not demote" in lowered
    assert "not" in lowered and "promote authority" in lowered
    assert "gitlab-grade" not in lowered
    assert "git required to promote" not in lowered
    assert "git is required to promote" not in lowered
    assert "open-source" not in lowered
    assert "open source" not in lowered
    assert " oss" not in lowered and not lowered.startswith("oss")
    assert INCUMBENT_RE.search(text) is None


def test_cross_links_and_module_pointer() -> None:
    import decision_api.promote_gitops as mod

    assert "pack-promote-export-v1" in (mod.__doc__ or "")
    lock = (REPO / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
    assert "pack-promote-export-v1.md" in lock
    gitops = (REPO / "docs/docs/guides/pack-gitops.md").read_text(encoding="utf-8")
    assert "pack-promote-export-v1.md" in gitops
    assert "desk Promote" in gitops
    support = (REPO / "SUPPORT.md").read_text(encoding="utf-8")
    assert "pack-promote-export-v1.md" in support
    assert "Desk Promote remains the live source of truth" in support
