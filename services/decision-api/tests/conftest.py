"""Ensure tests/ is on sys.path for shared helpers (e.g. aggregate_fake_redis)."""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("OTEL_SDK_DISABLED", "1")
os.environ.setdefault("TARKA_JSON_RULES_ENGINE", "python")

if (
    not (os.environ.get("API_KEYS") or "").strip()
    and not (os.environ.get("OIDC_ISSUER") or "").strip()
):
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


def pytest_sessionfinish(session: "pytest.Session", exitstatus: int) -> None:
    """G5 guard: fail if a test dropped a sqlite file named ':memory:' in CWD.

    Some tests build sqlite URLs from strings; a cwd-relative ':memory:' path
    creates a literal file named ':memory:' in whatever directory pytest ran
    from. That dirties the repo and recurs silently. Fail loudly instead.
    """
    import os

    stray = os.path.join(os.getcwd(), ":memory:")
    if os.path.isfile(stray):
        os.remove(stray)
        raise pytest.UsageError(
            f"stray sqlite artifact created and removed: {stray} (a test "
            "used a cwd-relative sqlite ':memory:' path; use "
            "sqlite+aiosqlite:///:memory: in-memory form or tmp_path)"
        )
