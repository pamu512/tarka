import pytest
from chitragupta.emitters import canonical_input_hash, emit_json, emit_with_retry


def test_canonical_input_hash_stable():
    a = canonical_input_hash({"b": 2, "a": 1})
    b = canonical_input_hash({"a": 1, "b": 2})
    assert a == b


def test_emit_json_deterministic_bytes():
    p = {"rows": [{"x": 1}], "tenant_id": "t1"}
    assert emit_json(p) == emit_json(p)


@pytest.mark.asyncio
async def test_emit_with_retry_succeeds_after_simulated_failures():
    data, log = await emit_with_retry(
        "json",
        {"k": "v"},
        max_attempts=4,
        base_delay=0.01,
        simulate_failures=2,
    )
    assert data.startswith(b"{")
    assert len(log) == 3
    assert log[-1]["ok"] is True
