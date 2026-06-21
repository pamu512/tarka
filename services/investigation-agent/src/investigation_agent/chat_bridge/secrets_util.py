from __future__ import annotations

import hmac


def constant_time_string_equals(expected: str, received: str | None) -> bool:
    """Compare UTF-8 secrets in constant time when lengths match; else False."""
    a = (expected or "").encode("utf-8")
    b = (received or "").encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)
