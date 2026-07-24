"""Deterministic OKF exporters and staging writes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from investigation_agent.okf_exporters import (
    LandmarkCaseSanitizationError,
    assert_staging_output_path,
    export_landmark_case,
    export_playbooks,
    export_rule_pack,
    export_typologies,
    render_concept,
    source_record_hash,
    write_staging_bundle,
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_REL_LINK = re.compile(r"\]\(([^)]+)\)")


def _frontmatter(md: str) -> dict:
    match = _FRONTMATTER.match(md)
    assert match, md
    meta = yaml.safe_load(match.group(1))
    assert isinstance(meta, dict)
    return meta


def test_render_concept_sorted_keys_and_trailing_newline():
    md = render_concept({"type": "Reference", "title": "T", "z_field": 1, "a_field": 2}, "body\n")
    assert md.endswith("\n")
    assert md.startswith("---\n")
    header = md.split("---\n")[1]
    assert "a_field" in header and header.index("a_field") < header.index("z_field")


def test_export_rule_pack_byte_identical_across_runs():
    pack = {
        "version": 1,
        "rules": [
            {
                "id": "sample_rule",
                "when": [{"op": "gte", "field": "amount", "value": 100}],
                "tags": ["high_value"],
                "score_delta": 10,
                "description": "Sample threshold",
            }
        ],
        "tag_rules": [],
    }
    first = export_rule_pack(pack, "rules/sample.json")
    second = export_rule_pack(pack, "rules/sample.json")
    assert first == second
    assert "rules/sample_rule.md" in first
    meta = _frontmatter(first["rules/sample_rule.md"])
    assert meta["source_uri"] == "rules/sample.json#sample_rule"
    assert meta["type"] == "Fraud Rule"
    assert meta["tenant_scope"] == "shared"


def test_one_byte_source_change_alters_source_content_hash():
    rule_a = {
        "id": "r1",
        "when": [],
        "tags": [],
        "score_delta": 1,
        "description": "alpha",
    }
    rule_b = dict(rule_a)
    rule_b["description"] = "alphb"
    pack_a = {"version": 1, "rules": [rule_a], "tag_rules": []}
    pack_b = {"version": 1, "rules": [rule_b], "tag_rules": []}
    hash_a = _frontmatter(export_rule_pack(pack_a, "rules/a.json")["rules/r1.md"])[
        "source_content_hash"
    ]
    hash_b = _frontmatter(export_rule_pack(pack_b, "rules/b.json")["rules/r1.md"])[
        "source_content_hash"
    ]
    assert hash_a != hash_b
    assert hash_a == source_record_hash(rule_a)
    assert hash_b == source_record_hash(rule_b)


def test_typology_exports_relative_rule_links():
    payload = {
        "version": 1,
        "typologies": [
            {
                "id": "velocity_abuse",
                "label": "Velocity abuse",
                "member_rule_ids": ["velocity_high_1h", "velocity_high_24h"],
                "weight_per_rule_hit": 35,
                "breach_thresholds": {"warning": 40, "alert": 75},
            }
        ],
    }
    files = export_typologies(payload, "rules/typology_definitions_v1.json")
    body = files["typologies/velocity_abuse.md"].split("---\n", 2)[2]
    hrefs = _REL_LINK.findall(body)
    assert hrefs
    assert all(not h.startswith("/") and "://" not in h for h in hrefs)
    assert "../rules/velocity_high_1h.md" in hrefs


def test_export_playbooks_deterministic():
    first = export_playbooks()
    second = export_playbooks()
    assert first == second
    assert first
    sample = next(iter(first.values()))
    meta = _frontmatter(sample)
    assert meta["type"] == "Investigation Playbook"
    assert meta["tenant_scope"] == "shared"


def test_landmark_case_rejects_unsanitized_pii():
    with pytest.raises(LandmarkCaseSanitizationError):
        export_landmark_case(
            {"case_id": "c1", "email": "person@example.com", "disposition": "fraud"},
            tenant_id="t1",
        )


def test_landmark_case_allowlist_only():
    case = {
        "case_id": "c1",
        "title": "Reviewed case",
        "typology_ids": ["velocity_abuse"],
        "rule_ids": ["velocity_high_1h"],
        "disposition": "fraud",
        "evidence_ids": ["ev-1"],
        "summary": "Sanitized summary.",
        "lessons": "Lesson learned.",
        "approved_revision": "rev-1",
        "source_content_hash": "c" * 64,
    }
    md = export_landmark_case(case, tenant_id="t1")
    meta = _frontmatter(md)
    assert meta["type"] == "Landmark Case"
    assert meta["tenant_scope"] == "t1"


def test_write_staging_bundle_refuses_active_shared_root(tmp_path):
    repo = tmp_path / "repo"
    active = repo / "knowledge" / "shared"
    active.mkdir(parents=True)
    with pytest.raises(ValueError, match="active"):
        assert_staging_output_path(active, repo_root=repo)


def test_write_staging_bundle_writes_only_under_root(tmp_path):
    staging = tmp_path / "var" / "okf-staging" / "shared"
    files = {
        "index.md": "---\nokf_version: '0.1'\n---\n# Staging\n",
        "rules/r1.md": render_concept(
            {
                "type": "Fraud Rule",
                "title": "R1",
                "source_uri": "rules/x.json#r1",
                "source_content_hash": "a" * 64,
                "approval_status": "approved",
                "approved_revision": "rev",
                "sensitivity": "internal",
                "tenant_scope": "shared",
            },
            "Body.",
        ),
    }
    write_staging_bundle(staging, files, repo_root=tmp_path)
    assert (staging / "rules" / "r1.md").read_text(encoding="utf-8") == files["rules/r1.md"]


def test_source_record_hash_stable_json():
    record = {"b": 2, "a": 1}
    expected = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    assert source_record_hash(record) == expected
