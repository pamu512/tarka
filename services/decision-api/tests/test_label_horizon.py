"""G5.2: tenant label-horizon policy is readable EXAMPLE config, not morals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from decision_api.gnn_loop.late_label import (
    LABEL_KINDS,
    LateLabelError,
    normalize_label_kind,
)


def test_unknown_label_kind_still_422() -> None:
    from decision_api.label_horizon import require_known_label_kind

    with pytest.raises(HTTPException) as exc:
        require_known_label_kind("not_a_kind")
    assert exc.value.status_code == 422
    with pytest.raises(LateLabelError) as late:
        normalize_label_kind("not_a_kind")
    assert late.value.code == "invalid_label_kind"


def test_example_horizons_readable_per_kind() -> None:
    from decision_api.label_horizon import horizon_days, horizon_policy

    policy = horizon_policy()
    assert policy["schema_id"] == "tarka.label_horizon/v1"
    assert policy["example"] is True
    assert policy["policy_owner"] == "tenant"
    assert policy["unit"] == "days"
    by_kind = policy["by_kind"]
    assert set(by_kind) == set(LABEL_KINDS)
    assert by_kind["promo_abuse"]["window_days"] >= 1
    assert by_kind["collusion"]["window_days"] >= 1
    assert by_kind["chargeback"]["window_days"] == 90
    assert by_kind["fp"]["window_days"] >= 1
    assert horizon_days("chargeback") == 90
    assert horizon_days("promo_abuse") == by_kind["promo_abuse"]["window_days"]
    assert "guarantee" not in json.dumps(policy).lower()


def test_env_horizon_override_keeps_unknown_kinds_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decision_api import label_horizon

    monkeypatch.setenv(
        "TARKA_LABEL_HORIZON_JSON",
        json.dumps(
            {
                "chargeback": {"window_days": 120},
                "not_a_kind": {"window_days": 3},
            }
        ),
    )
    policy = label_horizon.horizon_policy()
    assert policy["by_kind"]["chargeback"]["window_days"] == 120
    assert "not_a_kind" not in policy["by_kind"]
    assert (
        label_horizon.horizon_days("promo_abuse")
        == label_horizon.EXAMPLE_HORIZONS_DAYS["promo_abuse"]
    )


def test_desk_provision_horizon_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from desk_provision import SCHEMA_ID

    from decision_api import label_horizon

    path = tmp_path / "desk_provision.json"
    path.write_text(
        json.dumps(
            {
                "schema_id": SCHEMA_ID,
                "label_horizons": {
                    "collusion": {"window_days": 21},
                    "promo_abuse": {"window_days": 5},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.delenv("TARKA_LABEL_HORIZON_JSON", raising=False)
    assert label_horizon.horizon_days("collusion") == 21
    assert label_horizon.horizon_days("promo_abuse") == 5
    assert label_horizon.horizon_days("chargeback") == 90


def test_horizon_docs_are_tenant_policy_examples() -> None:
    root = Path(__file__).resolve().parents[3]
    join = (root / "docs/contracts/label-join-v1.md").read_text(encoding="utf-8")
    sop = (root / "docs/docs/guides/bakeoff-sop.md").read_text(encoding="utf-8")
    lock = (root / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
    help_page = (root / "frontend/src/pages/Help.tsx").read_text(encoding="utf-8")
    blob = f"{join}\n{sop}\n{lock}\n{help_page}".lower()
    assert "window_days" in join
    assert "promo_abuse" in join
    assert "collusion" in join
    assert "chargeback" in join
    assert "tenant policy" in blob
    assert "example" in blob
    assert (
        "guarantee" not in join.lower() or "not a chargeback-guarantee" in join.lower()
    )
    assert "auto-demote" in blob or "auto demote" in blob
    assert "tarka.label_horizon/v1" in join
