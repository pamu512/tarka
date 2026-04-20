"""Pytest env: TestClient calls omit X-API-Key; align with shared auth_rbac / require_api_key."""

import os

# auth_rbac and investigation-agent require_api_key fail closed when keys are configured but
# no header is sent. CI may export empty or inherited API_KEYS; enable insecure dev auth when unset.
if not (os.environ.get("API_KEYS") or "").strip() and not (os.environ.get("OIDC_ISSUER") or "").strip():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
