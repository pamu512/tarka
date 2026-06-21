"""OSINT **VendorSignalCache** (stable import path).

Implementation: ``tarka_vendor_finops.cache``.

Redis keys: ``vendorsig:{tenant}:{vendor}:{url_hash}`` with JSON bodies:

- **Positive** — ``{"__meta__": {"negative": false}, "payload": {...}}`` for successful vendor JSON.
- **Negative** — ``{"__meta__": {"negative": true, "status_code", "error_class", "message"}, "payload": null}`` so 404/5xx and transport failures are cached at the **same TTL** as the signal class (IP vs email, etc.), preventing expensive retry storms.

TTL selection: ``cache_ttl_for_vendor`` maps ``vendor_key`` → signal kind (IP / email / phone / domain / identity) with defaults **86400s (24h)** for IP-like and **604800s (7d)** for email-like unless overridden.
"""

from tarka_vendor_finops.cache import (
    DEFAULT_TTLS,
    VENDOR_SIGNAL_KIND,
    SignalKind,
    VendorSignalCache,
    cache_ttl_for_vendor,
)

__all__ = [
    "DEFAULT_TTLS",
    "SignalKind",
    "VENDOR_SIGNAL_KIND",
    "VendorSignalCache",
    "cache_ttl_for_vendor",
]
