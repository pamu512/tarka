#!/usr/bin/env python3
"""Wave 6: integrity / tamper posture evidence gate (docs + code + ops surface)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    checks: list[tuple[str, bool]] = []
    pinning = _REPO / "docs" / "docs" / "guides" / "tls-pinning-and-signed-requests.md"
    checks.append(("tls-pinning guide", pinning.is_file()))
    mw = (
        _REPO
        / "services"
        / "decision-api"
        / "src"
        / "decision_api"
        / "request_signature_middleware.py"
    )
    checks.append(("request signature middleware", mw.is_file()))
    if mw.is_file():
        text = mw.read_text(encoding="utf-8")
        checks.append(("middleware rejects invalid signature", "401" in text))
    main_py = (
        _REPO / "services" / "decision-api" / "src" / "decision_api" / "main.py"
    ).read_text(encoding="utf-8")
    checks.append(("attestation challenge route", "/v1/attestation/challenge" in main_py))
    checks.append(("attestation verify route", "/v1/attestation/verify" in main_py))
    ops = _REPO / "frontend" / "src" / "pages" / "OpsIntegrity.tsx"
    checks.append(("OpsIntegrity UI", ops.is_file()))
    gate = _REPO / "scripts" / "audit_request_signature_gate.py"
    checks.append(("HMAC CI gate script", gate.is_file()))
    redis = (
        _REPO / "services" / "decision-api" / "src" / "decision_api" / "redis_store.py"
    ).read_text(encoding="utf-8")
    checks.append(
        ("replay signature helper", "check_and_store_replay_signature" in redis)
    )

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")
    if failed:
        print("audit_integrity_posture: FAIL", file=sys.stderr)
        return 1
    print("audit_integrity_posture: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
