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
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ASSIST_HEADING = "### Pack GitOps export assist"


def _contract_event_name() -> str:
    text = CONTRACT.read_text(encoding="utf-8")
    match = re.search(r"Event name:\s+`([^`]+)`", text)
    assert match, "pack-promote-export-v1.md must name Event name"
    return match.group(1)


def test_schema_id_is_v1() -> None:
    assert SCHEMA_ID == "tarka.pack_promote_export/v1"


def test_schema_id_constant_matches_contract() -> None:
    assert SCHEMA_ID == _contract_event_name()
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


def test_human_promote_emits_schema_id_and_required_fields(tmp_path, monkeypatch) -> None:
    from decision_api.config import settings
    from decision_api.json_rules import load_rules
    from decision_api.shadow_auto_promote import activate_shadow_pack

    dest = tmp_path / "promote_export.jsonl"
    monkeypatch.setenv("PACK_GITOPS_EXPORT_PATH", str(dest))
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "pack-a.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "pack-a",
                "mode": "shadow",
                "pack_hash": "abc",
                "rules": [
                    {
                        "id": "r1",
                        "when": [{"field": "amount", "op": "gt", "value": 0}],
                        "score_delta": 1.0,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    load_rules()
    out = activate_shadow_pack(
        "pack-a",
        actor="analyst",
        reason="promote_shadow_pack",
    )
    assert out["promoted"] is True
    assert out["mode"] == "active"
    assert dest.is_file(), "human Promote must append promote_export"
    stored = json.loads(dest.read_text(encoding="utf-8").strip())
    assert stored["schema_id"] == SCHEMA_ID
    assert stored["schema_id"] == _contract_event_name()
    assert set(stored) == set(REQUIRED_FIELDS)
    for field in REQUIRED_FIELDS:
        assert field in stored
    assert stored["pack_id"] == "pack-a"
    assert stored["pack_hash"] == "abc"
    assert stored["mode"] == "active"
    assert stored["actor"] == "analyst"
    assert stored["reason"] == "promote_shadow_pack"
    assert stored["file"] == "pack-a.json"
    assert stored["emitted_at"]


def test_shadow_auto_promote_default_remains_false() -> None:
    from decision_api.shadow_auto_promote import default_provision

    assert default_provision("t1")["auto_promote"] is False
    src = (
        REPO / "services/decision-api/src/decision_api/shadow_auto_promote.py"
    ).read_text(encoding="utf-8")
    default_fn = src.split("def default_provision")[1].split("\ndef ")[0]
    assert '"auto_promote": False' in default_fn
    assert '"auto_promote": True' not in default_fn


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


def _section_after(text: str, heading: str) -> str:
    start = text.index(heading)
    body = text[start:]
    rest = body[len(heading) :]
    nxt = re.search(r"\n#{1,3} ", rest)
    return heading + (rest[: nxt.start()] if nxt else rest)


def _assert_rel_links(doc: Path, excerpt: str) -> None:
    for href in MD_LINK_RE.findall(excerpt):
        target = href.split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (doc.parent / target).resolve()
        assert resolved.exists(), f"broken link {href} from {doc}"


def test_support_export_assist_runbook_and_links() -> None:
    support = REPO / "SUPPORT.md"
    text = support.read_text(encoding="utf-8")
    assert ASSIST_HEADING in text
    section = _section_after(text, ASSIST_HEADING)
    lowered = section.lower()
    assert "desk promote" in lowered
    assert "backup" in lowered
    assert "pack-promote-export-v1.md" in section
    assert "pack-promote-export-consumer.md" in section
    assert "do not require a git merge" in lowered
    assert "gitlab-grade" not in lowered
    assert "git required to promote" not in lowered
    assert "git is required to promote" not in lowered
    assert "open-source" not in lowered
    assert "open source" not in lowered
    assert " oss" not in lowered and not lowered.startswith("oss")
    assert INCUMBENT_RE.search(section) is None
    _assert_rel_links(support, section)
    gitops = REPO / "docs/docs/guides/pack-gitops.md"
    gitops_text = gitops.read_text(encoding="utf-8")
    assert "SUPPORT.md#pack-gitops-export-assist" in gitops_text
    _assert_rel_links(gitops, gitops_text)
    example = REPO / "docs/examples/pack-promote-export-consumer.md"
    example_text = example.read_text(encoding="utf-8")
    assert "SUPPORT.md#pack-gitops-export-assist" in example_text
    _assert_rel_links(example, example_text)


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


def _tip_table_row(lock: str, needle: str) -> tuple[str, str]:
    start = lock.index("## Tip claims")
    table = lock[start:]
    end = table.find("\n**Provision")
    if end != -1:
        table = table[:end]
    for line in table.splitlines():
        if needle not in line or not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) != 2:
            continue
        if cols[0].startswith("True on tip") or cols[0].startswith("------"):
            continue
        return cols[0], cols[1]
    raise AssertionError(f"tip-table row missing {needle}")


def test_claim_lock_tip_table_export_is_backup_never_go_live_gate() -> None:
    lock = (REPO / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
    true_side, must_not = _tip_table_row(lock, "tarka.pack_promote_export/v1")
    true_l = true_side.lower()
    must_l = must_not.lower()
    assert "desk" in true_l and "promote" in true_l
    assert "sot" in true_l or "source of truth" in true_l
    assert "backup" in true_l
    assert "never" in true_l and "go-live gate" in true_l
    assert "git" in true_l
    assert true_side.strip() and must_not.strip()
    assert "git merge" in must_l
    assert "go-live gate" in must_l
    assert "promote authority" in must_l
    assert "demote" in must_l
    assert INCUMBENT_RE.search(true_side) is None
    assert INCUMBENT_RE.search(must_not) is None
    assert "open-source" not in true_l and "open source" not in true_l
    assert " oss" not in true_l
