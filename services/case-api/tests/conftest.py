"""Case API test defaults: SQLite + API key so HTTP tests can hit the app without Docker Postgres."""

import os
import sys
from pathlib import Path

# Prefer src/case_api over hoisted flat modules (avoid duplicate SQLAlchemy model registration).
_service_root = str(Path(__file__).resolve().parents[1])
_src_root = str(Path(__file__).resolve().parents[1] / "src")


def _strip_hoisted_service_root() -> None:
    while _service_root in sys.path:
        sys.path.remove(_service_root)
    if _src_root not in sys.path:
        sys.path.insert(0, _src_root)


_strip_hoisted_service_root()


def pytest_configure(config):  # noqa: ARG001
    _strip_hoisted_service_root()


# Default to in-memory SQLite (init_db create_all) unless the runner exports DATABASE_URL.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# API key grants admin (satisfies analyst-only routes); override locally if needed.
# CI often exports API_KEYS=""; setdefault does not replace empty strings.
if not (os.environ.get("API_KEYS") or "").strip():
    os.environ["API_KEYS"] = "case-api-test-key"
# Disable background retention sweeps during pytest (avoids races with in-memory DB lifecycle).
os.environ.setdefault("CASE_RETENTION_DAYS", "0")

# auth_rbac middleware requires API_KEYS, OIDC, or ALLOW_INSECURE_NO_AUTH.
if (
    not (os.environ.get("API_KEYS") or "").strip()
    and not (os.environ.get("OIDC_ISSUER") or "").strip()
):
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
