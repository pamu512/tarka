"""Signal lineage YAML crawler (compiler rule set format)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tarka_management.signal_lineage import scan_yaml_rules_tree


def _sample_rules_yaml() -> str:
    return """
version: 1
rules:
  - id: high_value_wire
    expression:
      kind: and
      children:
        - kind: compare_signal
          signal_name: payment_amount_usd
          op: gte
          expected: 5000
        - kind: compare_signal
          signal_name: payment_risk_score
          op: gte
          expected: 70
  - id: geo_block
    expression:
      kind: compare_signal
      signal_name: ip_country
      op: eq
      expected: "XX"
"""


def test_scan_extracts_compare_signal_leaves(tmp_path: Path) -> None:
    root = tmp_path / "yaml_rules"
    root.mkdir()
    text = _sample_rules_yaml()
    (root / "fraud.yaml").write_text(text, encoding="utf-8")

    result = scan_yaml_rules_tree(root)

    assert result.scan_summary["rule_bindings"] == 2
    assert "payment_amount_usd" in result.impact_by_signal
    assert "payment_risk_score" in result.impact_by_signal
    rule_ids = {r["rule_id"] for r in result.rules}
    assert rule_ids == {"high_value_wire", "geo_block"}
    hv = next(r for r in result.rules if r["rule_id"] == "high_value_wire")
    assert set(hv["signals"]) == {"payment_amount_usd", "payment_risk_score"}


def test_skips_disabled_directory(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    active = root / "active.yaml"
    active.write_text(
        """
version: 1
rules:
  - id: a
    expression:
      kind: compare_signal
      signal_name: ok_signal
      op: eq
      expected: 1
""",
        encoding="utf-8",
    )
    dis = root / "disabled"
    dis.mkdir()
    (dis / "ignored.yaml").write_text(
        """
version: 1
rules:
  - id: ignored
    expression:
      kind: compare_signal
      signal_name: bad_signal
      op: eq
      expected: 1
""",
        encoding="utf-8",
    )

    result = scan_yaml_rules_tree(root)
    signals = set(result.impact_by_signal.keys())
    assert signals == {"ok_signal"}
    assert "bad_signal" not in signals


def test_unknown_expression_kind_surfaces_error(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "bad.yaml").write_text(
        """
version: 1
rules:
  - id: broken
    expression:
      kind: mystery_leaf
      foo: bar
""",
        encoding="utf-8",
    )

    result = scan_yaml_rules_tree(root)
    assert result.scan_summary["rule_bindings"] == 1
    files = {f["path"]: f for f in result.files_scanned}
    assert "bad.yaml" in files
    assert any("unknown expression kind" in e for e in files["bad.yaml"]["errors"])
