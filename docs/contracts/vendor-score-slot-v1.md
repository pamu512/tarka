# Vendor score slot v1

Optional feature `vendor_score` / `vendor_decision` from `VENDOR_SCORE_URL`. Empty URL = off.

Timeout / error → fail-soft (no evaluate hard-fail). Pack rules still decide. The vendor score never silently overrides handoff enforcement.

Tarka does not bundle or resell third-party score vendors as a SKU.
