"""Case API test defaults: ensure auth dependency can succeed in CI."""

import os

# auth_rbac middleware requires API_KEYS, OIDC, or ALLOW_INSECURE_NO_AUTH.
if not (os.environ.get("API_KEYS") or "").strip() and not (os.environ.get("OIDC_ISSUER") or "").strip():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
