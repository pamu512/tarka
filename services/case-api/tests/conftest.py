"""Case API test defaults: SQLite + API key so HTTP tests can hit the app without Docker Postgres."""

import os

# Default to in-memory SQLite (init_db create_all) unless the runner exports DATABASE_URL.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# API key grants admin (satisfies analyst-only routes); override locally if needed.
os.environ.setdefault("API_KEYS", "case-api-test-key")
# Disable background retention sweeps during pytest (avoids races with in-memory DB lifecycle).
os.environ.setdefault("CASE_RETENTION_DAYS", "0")

# auth_rbac middleware requires API_KEYS, OIDC, or ALLOW_INSECURE_NO_AUTH.
if not (os.environ.get("API_KEYS") or "").strip() and not (os.environ.get("OIDC_ISSUER") or "").strip():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
