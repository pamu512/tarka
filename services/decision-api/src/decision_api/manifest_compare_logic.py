"""Deep diff for EvidenceManifest execution traces (production vs shadow debugging)."""

from __future__ import annotations

import math
from typing import Any, Literal

Side = Literal["manifest_a", "manifest_b"]


def leaf_equal(a: Any, b: Any) -> bool:
    """Leaf equality for snapshots (float-safe); does not recurse into dict/list."""
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) or isinstance(b, float):
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
        return int(a) == int(b)
    return a == b


def deep_diff_structural(left: Any, right: Any, *, path: str = "") -> dict[str, Any]:
    """Recursive JSON-like diff: surfaces only_in_left / only_in_right / value_mismatch."""
    if isinstance(left, dict) and isinstance(right, dict):
        keys = set(left.keys()) | set(right.keys())
        children: dict[str, Any] = {}
        mismatches = 0
        for k in sorted(keys, key=str):
            kp = f"{path}.{k}" if path else f"$.{k}"
            if k not in left:
                children[str(k)] = {
                    "match": False,
                    "kind": "only_in_right",
                    "path": kp,
                    "right": right[k],
                }
                mismatches += 1
            elif k not in right:
                children[str(k)] = {
                    "match": False,
                    "kind": "only_in_left",
                    "path": kp,
                    "left": left[k],
                }
                mismatches += 1
            else:
                sub = deep_diff_structural(left[k], right[k], path=kp)
                children[str(k)] = sub
                if not sub.get("match"):
                    mismatches += 1
        return {
            "match": mismatches == 0,
            "kind": "object",
            "path": path or "$",
            "keys_compared": len(keys),
            "children": children,
        }

    if isinstance(left, list) and isinstance(right, list):
        max_len = max(len(left), len(right))
        items: list[Any] = []
        mismatches = 0
        for i in range(max_len):
            kp = f"{path}[{i}]" if path else f"$[{i}]"
            if i >= len(left):
                items.append(
                    {
                        "match": False,
                        "kind": "only_in_right",
                        "path": kp,
                        "index": i,
                        "right": right[i],
                    }
                )
                mismatches += 1
            elif i >= len(right):
                items.append(
                    {
                        "match": False,
                        "kind": "only_in_left",
                        "path": kp,
                        "index": i,
                        "left": left[i],
                    }
                )
                mismatches += 1
            else:
                sub = deep_diff_structural(left[i], right[i], path=kp)
                items.append(sub)
                if not sub.get("match"):
                    mismatches += 1
        return {
            "match": mismatches == 0,
            "kind": "array",
            "path": path or "$",
            "length_left": len(left),
            "length_right": len(right),
            "items": items,
        }

    if leaf_equal(left, right):
        return {"match": True, "path": path or "$"}

    return {
        "match": False,
        "kind": "value_mismatch",
        "path": path or "$",
        "left": left,
        "right": right,
        "left_type": type(left).__name__,
        "right_type": type(right).__name__,
    }


def _diff_one_step(
    step_a: dict[str, Any],
    step_b: dict[str, Any],
    step_index: int,
) -> dict[str, Any]:
    snap_diff = deep_diff_structural(
        step_a.get("state_snapshot_decoded") or {},
        step_b.get("state_snapshot_decoded") or {},
        path=f"$.steps[{step_index}].state_snapshot_decoded",
    )
    rule_match = step_a.get("rule_id") == step_b.get("rule_id")
    result_match = step_a.get("result") == step_b.get("result")
    logic_match = step_a.get("logic_operator") == step_b.get("logic_operator")
    operands_match = step_a.get("operands") == step_b.get("operands")

    identical = (
        rule_match
        and result_match
        and logic_match
        and operands_match
        and snap_diff.get("match") is True
    )

    fields = {
        "rule_id": {
            "match": rule_match,
            "manifest_a": step_a.get("rule_id"),
            "manifest_b": step_b.get("rule_id"),
        },
        "result": {
            "match": result_match,
            "manifest_a": step_a.get("result"),
            "manifest_b": step_b.get("result"),
        },
        "logic_operator": {
            "match": logic_match,
            "manifest_a": step_a.get("logic_operator"),
            "manifest_b": step_b.get("logic_operator"),
        },
        "operands": {
            "match": operands_match,
            "manifest_a": step_a.get("operands"),
            "manifest_b": step_b.get("operands"),
        },
        "state_snapshot_raw": {
            "match": step_a.get("state_snapshot") == step_b.get("state_snapshot"),
        },
        "state_snapshot_decoded": snap_diff,
    }

    return {
        "step_index": step_index,
        "identical": identical,
        "fields": fields,
    }


def _step_equality_rank_for_divergence(
    step_a: dict[str, Any],
    step_b: dict[str, Any],
) -> tuple[bool, str | None]:
    """Return (steps_equivalent_for_alignment, first_divergence_category).

    Ordering decides which difference is the primary fork for analysts:
    rule identity → boolean outcome → intermediate state → structural details.
    """
    if step_a.get("rule_id") != step_b.get("rule_id"):
        return False, "rule_id"
    if step_a.get("result") != step_b.get("result"):
        return False, "rule_boolean_result"
    snap_match = deep_diff_structural(
        step_a.get("state_snapshot_decoded") or {},
        step_b.get("state_snapshot_decoded") or {},
    ).get("match")
    if not snap_match:
        return False, "intermediate_state"
    if step_a.get("logic_operator") != step_b.get("logic_operator"):
        return False, "logic_operator"
    if step_a.get("operands") != step_b.get("operands"):
        return False, "operands"
    if step_a.get("state_snapshot") != step_b.get("state_snapshot"):
        return False, "state_snapshot_raw"
    return True, None


def find_divergence_explanation(
    steps_a: list[dict[str, Any]],
    steps_b: list[dict[str, Any]],
    *,
    final_decision_a: bool,
    final_decision_b: bool,
) -> dict[str, Any]:
    """Locate first semantic fork and attribute a culprit rule when possible."""
    decisions_match = final_decision_a == final_decision_b
    len_a, len_b = len(steps_a), len(steps_b)

    first_idx: int | None = None
    category: str | None = None
    aligned_through = min(len_a, len_b)

    for i in range(aligned_through):
        eq, cat = _step_equality_rank_for_divergence(steps_a[i], steps_b[i])
        if not eq:
            first_idx = i
            category = cat
            break

    if first_idx is None and len_a != len_b:
        first_idx = min(len_a, len_b)
        category = "execution_path_length"

    culprit_rule_id: str | None = None
    culprit_manifest: Side | None = None
    human = ""

    if first_idx is None:
        if not decisions_match:
            return {
                "decisions_match": False,
                "paths_structurally_identical": True,
                "first_divergence_step_index": None,
                "divergence_category": "metadata_final_decision_only",
                "culprit_rule_id": None,
                "culprit_manifest_side": None,
                "human_readable": (
                    "Trace steps match pairwise but metadata.final_decision differs — "
                    "investigate engine metadata vs trace aggregation."
                ),
            }
        return {
            "decisions_match": True,
            "paths_structurally_identical": True,
            "first_divergence_step_index": None,
            "divergence_category": None,
            "culprit_rule_id": None,
            "culprit_manifest_side": None,
            "human_readable": "Manifests are identical on execution path and final_decision.",
        }

    if category == "execution_path_length":
        if len_a > len_b:
            culprit_rule_id = steps_a[first_idx]["rule_id"]
            culprit_manifest = "manifest_a"
            human = (
                f"Manifest A continues after step {first_idx - 1}; first extra rule on A is "
                f"'{culprit_rule_id}' at step index {first_idx}."
            )
        else:
            culprit_rule_id = steps_b[first_idx]["rule_id"]
            culprit_manifest = "manifest_b"
            human = (
                f"Manifest B continues after step {first_idx - 1}; first extra rule on B is "
                f"'{culprit_rule_id}' at step index {first_idx}."
            )
        return {
            "decisions_match": decisions_match,
            "paths_structurally_identical": False,
            "first_divergence_step_index": first_idx,
            "divergence_category": category,
            "culprit_rule_id": culprit_rule_id,
            "culprit_manifest_side": culprit_manifest,
            "human_readable": human,
        }

    sa, sb = steps_a[first_idx], steps_b[first_idx]

    if category == "rule_id":
        culprit_rule_id = sa["rule_id"]
        human = (
            f"At step {first_idx}, rule ids diverge: A='{sa['rule_id']}' vs B='{sb['rule_id']}' "
            "(evaluation order or pack differs)."
        )
        return {
            "decisions_match": decisions_match,
            "paths_structurally_identical": False,
            "first_divergence_step_index": first_idx,
            "divergence_category": category,
            "culprit_rule_id": culprit_rule_id,
            "culprit_manifest_side": None,
            "paired_rule_id_other_manifest": sb["rule_id"],
            "human_readable": human,
        }

    if category == "rule_boolean_result":
        culprit_rule_id = sa["rule_id"]
        human = (
            f"Rule '{culprit_rule_id}' at step {first_idx} evaluated to "
            f"{sa['result']} in manifest A and {sb['result']} in manifest B — "
            f"primary suspect for downstream decision divergence."
        )
        return {
            "decisions_match": decisions_match,
            "paths_structurally_identical": False,
            "first_divergence_step_index": first_idx,
            "divergence_category": category,
            "culprit_rule_id": culprit_rule_id,
            "culprit_manifest_side": None,
            "human_readable": human,
        }

    if category == "intermediate_state":
        culprit_rule_id = sa["rule_id"]
        human = (
            f"Rule '{culprit_rule_id}' at step {first_idx} produced differing intermediate "
            f"state_snapshot (decoded) while boolean result still matches."
        )
        return {
            "decisions_match": decisions_match,
            "paths_structurally_identical": False,
            "first_divergence_step_index": first_idx,
            "divergence_category": category,
            "culprit_rule_id": culprit_rule_id,
            "culprit_manifest_side": None,
            "human_readable": human,
        }

    if category in ("logic_operator", "operands", "state_snapshot_raw"):
        culprit_rule_id = sa["rule_id"]
        human = (
            f"Rule '{culprit_rule_id}' at step {first_idx} differs on {category.replace('_', ' ')}."
        )
        return {
            "decisions_match": decisions_match,
            "paths_structurally_identical": False,
            "first_divergence_step_index": first_idx,
            "divergence_category": category,
            "culprit_rule_id": culprit_rule_id,
            "culprit_manifest_side": None,
            "human_readable": human,
        }

    return {
        "decisions_match": decisions_match,
        "paths_structurally_identical": False,
        "first_divergence_step_index": first_idx,
        "divergence_category": category or "unknown",
        "culprit_rule_id": None,
        "culprit_manifest_side": None,
        "human_readable": f"Divergence detected at step {first_idx}.",
    }


def diff_signals_maps(
    sig_a: dict[str, Any],
    sig_b: dict[str, Any],
) -> dict[str, Any]:
    """Deep diff for input Map(String,String) signal maps."""
    return deep_diff_structural(sig_a, sig_b, path="$.signals")


def build_full_manifest_comparison(
    *,
    manifest_id_a: str,
    manifest_id_b: str,
    bundle_a: dict[str, Any],
    bundle_b: dict[str, Any],
    steps_a: list[dict[str, Any]],
    steps_b: list[dict[str, Any]],
    final_a: bool,
    final_b: bool,
) -> dict[str, Any]:
    """Assemble API payload: aligned step diffs, signals diff, divergence narrative."""
    sig_a = bundle_a.get("signals") if isinstance(bundle_a.get("signals"), dict) else {}
    sig_b = bundle_b.get("signals") if isinstance(bundle_b.get("signals"), dict) else {}

    step_rows: list[dict[str, Any]] = []
    max_idx = max(len(steps_a), len(steps_b))
    for i in range(max_idx):
        if i >= len(steps_a):
            step_rows.append(
                {
                    "step_index": i,
                    "alignment": "only_manifest_b",
                    "manifest_a": None,
                    "manifest_b": {
                        k: v
                        for k, v in steps_b[i].items()
                        if k in ("rule_id", "logic_operator", "operands", "result", "state_snapshot", "state_snapshot_decoded")
                    },
                }
            )
            continue
        if i >= len(steps_b):
            step_rows.append(
                {
                    "step_index": i,
                    "alignment": "only_manifest_a",
                    "manifest_a": {
                        k: v
                        for k, v in steps_a[i].items()
                        if k in ("rule_id", "logic_operator", "operands", "result", "state_snapshot", "state_snapshot_decoded")
                    },
                    "manifest_b": None,
                }
            )
            continue
        step_rows.append(
            {
                "step_index": i,
                "alignment": "both",
                **_diff_one_step(steps_a[i], steps_b[i], i),
            }
        )

    divergence = find_divergence_explanation(
        steps_a,
        steps_b,
        final_decision_a=final_a,
        final_decision_b=final_b,
    )

    metadata_diff = {
        "final_decision": {
            "match": final_a == final_b,
            "manifest_a": final_a,
            "manifest_b": final_b,
        },
        "engine_version": {
            "match": bundle_a.get("engine_version") == bundle_b.get("engine_version"),
            "manifest_a": bundle_a.get("engine_version"),
            "manifest_b": bundle_b.get("engine_version"),
        },
        "timestamp_ns": {
            "match": bundle_a.get("timestamp_ns") == bundle_b.get("timestamp_ns"),
            "manifest_a": bundle_a.get("timestamp_ns"),
            "manifest_b": bundle_b.get("timestamp_ns"),
        },
        "total_execution_time_us": {
            "match": bundle_a.get("total_execution_time_us")
            == bundle_b.get("total_execution_time_us"),
            "manifest_a": bundle_a.get("total_execution_time_us"),
            "manifest_b": bundle_b.get("total_execution_time_us"),
        },
        "signals": diff_signals_maps(sig_a, sig_b),
    }

    return {
        "manifest_id_a": manifest_id_a,
        "manifest_id_b": manifest_id_b,
        "path_lengths": {"manifest_a": len(steps_a), "manifest_b": len(steps_b)},
        "metadata_diff": metadata_diff,
        "intermediate_states_and_execution_path": step_rows,
        "divergence": divergence,
    }
