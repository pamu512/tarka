"""Integration ingress tests: shared auth must not fail closed when CI exports empty API_KEYS."""

import os

if not (os.environ.get("API_KEYS") or "").strip():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
