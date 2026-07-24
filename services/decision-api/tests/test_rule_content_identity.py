"""Phase 1: content-addressed rule identity changes when rule body changes."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from decision_api.rule_content_identity import (  # noqa: E402
    packs_content_sha256,
    rule_pack_content_sha256,
)


def test_one_byte_rule_edit_changes_content_identity() -> None:
    a = {
        "version": 1,
        "name": "demo",
        "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gte", "value": 100}]}],
        "_source_file": "a.json",
    }
    b = {
        "version": 1,
        "name": "demo",
        "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gte", "value": 101}]}],
        "_source_file": "a.json",
    }
    assert rule_pack_content_sha256(a) != rule_pack_content_sha256(b)
    assert packs_content_sha256([a]) != packs_content_sha256([b])


def test_filename_alone_does_not_change_content_identity() -> None:
    a = {
        "version": 1,
        "name": "demo",
        "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gte", "value": 100}]}],
        "_source_file": "a.json",
    }
    b = {**a, "_source_file": "renamed.json"}
    assert rule_pack_content_sha256(a) == rule_pack_content_sha256(b)
