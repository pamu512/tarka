#!/usr/bin/env python3
"""Compare deployment env keys across compose, hardening overlay, and .env.example."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

ENV_KEY_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)
YAML_ENV_RE = re.compile(r"^\s*-\s*([A-Z][A-Z0-9_]*)(?:=|:)", re.MULTILINE)
COMPOSE_ENV_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*):\s", re.MULTILINE)

# Keys every production surface must document (Q1-E07 contract).
REQUIRED_DOCUMENTED = frozenset(
    {
        "DATABASE_URL",
        "REDIS_URL",
        "TENANT_BINDING_REQUIRED",
        "ALLOW_INSECURE_NO_AUTH",
        "FEATURE_SERVICE_URL",
        "ML_SCORING_URL",
        "GRAPH_SERVICE_URL",
        "DECISION_API_URL",
    }
)


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def keys_from_env_example(text: str) -> set[str]:
    return set(ENV_KEY_RE.findall(text))


def keys_from_compose(text: str) -> set[str]:
    found = set(COMPOSE_ENV_RE.findall(text))
    found.update(YAML_ENV_RE.findall(text))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.repo_root

    env_example = keys_from_env_example(_read(root / "infra/deploy/.env.example"))
    compose = keys_from_compose(_read(root / "infra/deploy/docker-compose.yml"))
    hardening = keys_from_compose(_read(root / "infra/deploy/docker-compose.production-hardening.yml"))

    missing_doc = REQUIRED_DOCUMENTED - env_example
    if missing_doc:
        print("FAIL: infra/deploy/.env.example missing documented keys:", sorted(missing_doc), file=sys.stderr)
        return 1

    missing_compose = REQUIRED_DOCUMENTED - compose
    if missing_compose:
        print(
            "FAIL: infra/deploy/docker-compose.yml missing env keys (services must set or inherit):",
            sorted(missing_compose),
            file=sys.stderr,
        )
        return 1

    missing_hardening = REQUIRED_DOCUMENTED - hardening - compose
    if missing_hardening:
        print(
            "WARN: production-hardening overlay does not re-declare (may inherit from base):",
            sorted(missing_hardening),
            file=sys.stderr,
        )

    print(
        f"OK: env contract — {len(REQUIRED_DOCUMENTED)} required keys documented; "
        f"compose covers {len(REQUIRED_DOCUMENTED - missing_compose)}/{len(REQUIRED_DOCUMENTED)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
