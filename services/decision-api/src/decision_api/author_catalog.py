"""Re-export shared author catalog (shadow_agent cannot import decision_api)."""

from author_catalog import (  # noqa: F401
    CATALOG_HOPS,
    IDENTITY_FIELDS,
    LEGACY_ALIASES,
    PAYLOAD_FIELDS,
    ai_allowed_fields,
    build_author_catalog,
    catalog_field_names,
    window_token,
)
