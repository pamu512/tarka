"""Central Schemathesis + Hypothesis settings for decision-api contract tests.

Environment variables
---------------------

``SCHEMATHESIS_CONTRACT_MIN_TOTAL`` (default ``100``)
    Lower bound on **Hypothesis examples per parametrized operation** × operations is not how
    Schemathesis splits work: each collected test node is one OpenAPI **operation**; within that
    node, Hypothesis draws up to ``max_examples`` ``Case`` values. Total generated API calls for
    ``@schema.parametrize()`` is therefore::

        operations_in_schema × max_examples

    We default ``max_examples`` so this product is **at least** ``SCHEMATHESIS_CONTRACT_MIN_TOTAL``
    unless ``SCHEMATHESIS_MAX_EXAMPLES`` is set explicitly.

``SCHEMATHESIS_MAX_EXAMPLES``
    Override auto-derived examples-per-operation (cap still applies).

``SCHEMATHESIS_MAX_EXAMPLES_CAP`` (default ``40``)
    Upper bound for auto-derived ``max_examples`` (prevents accidental huge CI runs).

``SCHEMATHESIS_BINARY_MAX_EXAMPLES`` (default ``80``)
    Hypothesis ``max_examples`` for binary / protobuf fuzz tests in
    ``test_binary_and_boundary_payloads.py``.

``SCHEMATHESIS_STRICT_RESPONSE_SCHEMA``
    When ``1`` / ``true``, enforce OpenAPI response body and content-type checks (full stack).
"""

from __future__ import annotations

import os
from functools import lru_cache

from hypothesis import HealthCheck, settings
from schemathesis.core.result import Ok


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def _openapi_operation_count() -> int:
    """Lazy import so collecting tests without decision-api deps does not always load the app."""
    from tests.contract.schemathesis_schemas import SCHEMA_FROM_APP

    n = 0
    for r in SCHEMA_FROM_APP.get_all_operations():
        if isinstance(r, Ok):
            n += 1
    return max(n, 1)


def derived_max_examples_for_min_total(
    *,
    min_total: int | None = None,
    cap: int | None = None,
) -> int:
    """Compute ``max_examples`` so ``operations × max_examples >= min_total`` (subject to cap)."""
    min_t = min_total if min_total is not None else _int_env("SCHEMATHESIS_CONTRACT_MIN_TOTAL", 100)
    cap_v = cap if cap is not None else _int_env("SCHEMATHESIS_MAX_EXAMPLES_CAP", 40)
    ops = _openapi_operation_count()
    # ceil(min_total / ops)
    need = (min_t + ops - 1) // ops
    return max(1, min(need, cap_v))


def contract_hypothesis_settings() -> settings:
    """Hypothesis settings for ``@schema.parametrize()`` contract tests."""
    if os.environ.get("SCHEMATHESIS_MAX_EXAMPLES", "").strip():
        max_ex = _int_env("SCHEMATHESIS_MAX_EXAMPLES", 5)
    else:
        max_ex = derived_max_examples_for_min_total()
    return settings(
        max_examples=max_ex,
        deadline=None,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
        ],
    )


def binary_fuzz_max_examples() -> int:
    return _int_env("SCHEMATHESIS_BINARY_MAX_EXAMPLES", 80)


def strict_response_schema_enabled() -> bool:
    return os.environ.get("SCHEMATHESIS_STRICT_RESPONSE_SCHEMA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def contract_generation_stats() -> dict[str, int]:
    """For assertions that the default budget meets ``SCHEMATHESIS_CONTRACT_MIN_TOTAL``."""
    ops = _openapi_operation_count()
    if os.environ.get("SCHEMATHESIS_MAX_EXAMPLES", "").strip():
        ex = _int_env("SCHEMATHESIS_MAX_EXAMPLES", 5)
    else:
        ex = derived_max_examples_for_min_total()
    floor = _int_env("SCHEMATHESIS_CONTRACT_MIN_TOTAL", 100)
    return {
        "operations": ops,
        "max_examples": ex,
        "min_total_floor": floor,
        "expected_min_calls": ops * ex,
    }
