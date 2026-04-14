"""Redis-backed aggregates; implementation in services/shared/fraud_aggregates.py."""

from __future__ import annotations

from fraud_aggregates import (
    AGG_PREFIX,
    AGG_VAL_PREFIX,
    DISTINCT_FIELDS,
    MAX_WINDOW,
    NUMERIC_FIELDS,
    AggregateStore,
)

agg_store = AggregateStore()

__all__ = [
    "AGG_PREFIX",
    "AGG_VAL_PREFIX",
    "MAX_WINDOW",
    "NUMERIC_FIELDS",
    "DISTINCT_FIELDS",
    "AggregateStore",
    "agg_store",
]
