"""Integration ingress tests: auth for RBAC-protected routes.

CI forces empty API_KEYS; ALLOW_INSECURE_NO_AUTH alone yields role *viewer*, but many
integration routes require analyst/admin. Use a deterministic test API key so
X-API-Key maps to service auth with SERVICE_API_KEY_ROLE (default admin in auth_rbac).
"""

import os

if not (os.environ.get("API_KEYS") or "").strip():
    os.environ["API_KEYS"] = "test-integration-key"
    os.environ["SERVICE_API_KEY_ROLE"] = "admin"
