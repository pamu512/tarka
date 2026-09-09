"""G4.1: emit_only default; signed webhook; both sides of CLAIM_LOCK honesty."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CLAIM = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"
_CONTRACT = _REPO / "docs" / "contracts" / "enforcement-v1.md"
_README = _REPO / "README.md"
_LICENSE = _REPO / "LICENSE"
_GUIDE = _REPO / "docs" / "docs" / "guides" / "decide-to-act-enforcement.md"

_HANDOFF_ASSIGN = re.compile(
    r"""TARKA_ENFORCEMENT_MODE\s*[:=]\s*['"]?handoff\b""",
    re.IGNORECASE,
)
_INCUMBENTS = re.compile(r"\b(Sift|Forter|Riskified|Feedzai|Featurespace)\b")

_DEFAULT_SCAN = (
    _REPO / "docker-compose.yml",
    _REPO / "docker-compose.local.yml",
    _REPO / "infra" / "deploy" / "docker-compose.yml",
    _REPO / "infra" / "deploy" / "docker-compose.lite.yml",
    _REPO / "infra" / "deploy" / "docker-compose.demo-vertical.yml",
    _REPO / "infra" / "deploy" / "docker-compose.full-desk.yml",
    _REPO / "infra" / "deploy" / "docker-compose.fraud-desk.yml",
    _REPO / "infra" / "deploy" / "docker-compose.product.yml",
    _REPO / "infra" / "deploy" / "docker-compose.micro.yml",
    _REPO / "infra" / "deploy" / ".env.example",
    _REPO / "infra" / "deploy" / "desk_provision.example.json",
    _REPO
    / "infra"
    / "deploy"
    / "helm"
    / "fraud-stack"
    / "templates"
    / "desk-provision.yaml",
)


def _active_lines(text: str) -> str:
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        out.append(raw)
    return "\n".join(out)


def test_claim_lock_enforcement_both_honesty_sides() -> None:
    text = _CLAIM.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "docs/contracts/enforcement-v1.md" in text
    assert "contract-gated" in lowered
    assert "emit-only" in lowered
    assert "handoff as day-1 default" in lowered
    assert "silent block in emit-only" in lowered
    assert "x-tarka-signature" in lowered
    assert "hmac-sha256" in lowered
    assert "unsigned" in lowered
    assert "ELv2" in text
    assert "not oss" in lowered
    assert "open-source" in lowered
    assert not _INCUMBENTS.search(text)


def test_enforcement_v1_signed_webhook_and_emit_only() -> None:
    text = _CONTRACT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "emit_only" in text
    assert "handoff" in text
    assert "enforcement.mode = emit_only" in text.replace("`", "")
    assert "x-tarka-signature" in lowered
    assert "hmac-sha256" in lowered
    assert "empty url" in lowered
    assert "we blocked" in lowered
    assert "does not implement" in lowered
    assert "payout" in lowered
    assert "promo" in lowered
    assert "courier" in lowered
    assert "case crm" in lowered
    assert "decision.emitted" in text
    assert "decision.enforced" in text
    assert not _INCUMBENTS.search(text)


def test_readme_enforcement_honesty_both_sides() -> None:
    text = _README.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "emit-only" in lowered
    assert "Handoff as Day-1 default" in text
    assert "silent block in emit-only" in text
    assert "x-tarka-signature" in lowered
    assert "ELv2" in text
    assert "not oss" in lowered
    assert not _INCUMBENTS.search(text)


def test_decide_to_act_documents_hmac_header() -> None:
    text = _GUIDE.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "x-tarka-signature" in lowered
    assert "hmac-sha256" in lowered
    assert "empty url" in lowered


def test_license_is_elv2_never_oss() -> None:
    text = _LICENSE.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:12])
    assert "Elastic License 2.0" in text
    assert "MIT License" not in head
    assert "Apache-2.0" not in head


def test_compose_and_demo_defaults_stay_emit_only() -> None:
    missing = [p for p in _DEFAULT_SCAN if not p.is_file()]
    assert not missing, f"missing scan targets: {missing}"
    for path in _DEFAULT_SCAN:
        active = _active_lines(path.read_text(encoding="utf-8"))
        assert not _HANDOFF_ASSIGN.search(active), (
            f"{path.relative_to(_REPO)} must not default TARKA_ENFORCEMENT_MODE=handoff"
        )
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            block = data.get("enforcement")
            if isinstance(block, dict):
                assert str(block.get("mode") or "emit_only") == "emit_only"


def test_desk_schema_does_not_default_handoff() -> None:
    schema = json.loads(
        (_REPO / "infra" / "deploy" / "desk_provision.schema.json").read_text(
            encoding="utf-8"
        )
    )
    props = schema.get("properties") or {}
    enf = props.get("enforcement") or {}
    mode = (enf.get("properties") or {}).get("mode") or {}
    if mode:
        assert mode.get("default", "emit_only") == "emit_only"
        assert "handoff" not in str(mode.get("default") or "")
