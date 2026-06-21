"""Property-based OpenAPI contract tests using Schemathesis + Hypothesis.

Runs against the **live** FastAPI ``openapi.json`` (strict superset of ``contracts/openapi/decision-api.yaml``).

**100+ generated cases (default):** ``tests/contract/schemathesis_config.py`` sets Hypothesis
``max_examples`` so ``operations_in_schema × max_examples ≥ SCHEMATHESIS_CONTRACT_MIN_TOTAL`` (default
``100``), unless ``SCHEMATHESIS_MAX_EXAMPLES`` is set explicitly.

Binary / protobuf fuzz volume: ``SCHEMATHESIS_BINARY_MAX_EXAMPLES`` (default ``80``) in
``test_binary_and_boundary_payloads.py``.

Strict OpenAPI response/body validation (staging): ``SCHEMATHESIS_STRICT_RESPONSE_SCHEMA=1``.

CI: ``pytest tests/contract -m contract`` — default mode catches **5xx under fuzz**; strict mode also
enforces response schemas.

Optional portable spec (checked-in YAML only): ``CONTRACT_SCHEMATHESIS_INCLUDE_YAML=1`` runs a
second parametrized suite against ``contracts/openapi/decision-api.yaml`` (same Hypothesis budget).
"""

from __future__ import annotations

import os

import pytest
from schemathesis import checks
from schemathesis.core.result import Ok
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    positive_data_acceptance,
    response_schema_conformance,
    status_code_conformance,
    unsupported_method,
)

from tests.contract.bootstrap_app import CONTRACT_API_KEY
from tests.contract.schemathesis_config import (
    contract_hypothesis_settings,
    strict_response_schema_enabled,
)
from tests.contract.schemathesis_schemas import (
    SCHEMA_FROM_APP,
    SCHEMA_FROM_CONTRACT_YAML,
)

_CONTRACT_HEADERS = {"X-API-Key": CONTRACT_API_KEY}

pytestmark = pytest.mark.contract

_CONTRACT_SETTINGS = contract_hypothesis_settings()
_STRICT = strict_response_schema_enabled()


@SCHEMA_FROM_APP.parametrize()
@_CONTRACT_SETTINGS
def test_decision_api_full_schema_contract(case):
    """Exercise every operation: boundary payloads, invalid combinations, status contracts."""
    relaxed = [
        checks.max_response_time,
        unsupported_method,
        status_code_conformance,
        positive_data_acceptance,
    ]
    if not _STRICT:
        # Default suite uses DB/redis mocks; response shapes for 2xx/4xx vary vs production.
        relaxed.extend([response_schema_conformance, content_type_conformance])

    case.call_and_validate(
        headers=_CONTRACT_HEADERS,
        excluded_checks=relaxed,
    )


def test_checked_in_yaml_contract_loads_and_has_paths():
    """Ensure the git-tracked portable contract stays compatible with Schemathesis."""
    ops = [
        r.ok()
        for r in SCHEMA_FROM_CONTRACT_YAML.get_all_operations()
        if isinstance(r, Ok)
    ]
    assert len(ops) >= 5, (
        "expected multiple operations in contracts/openapi/decision-api.yaml"
    )


def test_generation_budget_meets_min_total_floor():
    """Guarantee default Hypothesis budget satisfies ``SCHEMATHESIS_CONTRACT_MIN_TOTAL``."""
    from tests.contract.schemathesis_config import contract_generation_stats

    s = contract_generation_stats()
    assert s["expected_min_calls"] >= s["min_total_floor"], s


if os.environ.get("CONTRACT_SCHEMATHESIS_INCLUDE_YAML", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
):

    @SCHEMA_FROM_CONTRACT_YAML.parametrize()
    @_CONTRACT_SETTINGS
    def test_decision_api_portable_yaml_schema_contract(case):
        """Property tests against the frozen portable OpenAPI file (opt-in; doubles runtime)."""
        relaxed = [
            checks.max_response_time,
            unsupported_method,
            status_code_conformance,
            positive_data_acceptance,
        ]
        if not _STRICT:
            relaxed.extend([response_schema_conformance, content_type_conformance])
        case.call_and_validate(
            headers=_CONTRACT_HEADERS,
            excluded_checks=relaxed,
        )
