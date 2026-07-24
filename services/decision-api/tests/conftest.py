"""Configure the source decision-API suite against deployed rule assets."""

from __future__ import annotations

import os
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_DEPLOYED_RULES = _SERVICE_ROOT.parent / "legacy_v1_decision_api" / "rules"

os.environ.setdefault("RULES_PATH", str(_DEPLOYED_RULES))
os.environ.setdefault("TARKA_JSON_RULES_ENGINE", "python")
