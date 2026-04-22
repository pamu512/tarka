from __future__ import annotations

from typing import Any

"""Per-tenant kill switches (R2.3) — Redis JSON at fraud:tenant_flags:{tenant_id}."""

def tenant_flag_enabled(flags: dict[str, Any], key: str) -> bool:
    v = flags.get(key)
    if v is True:
        return True
    if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"):
        return True
    return False
