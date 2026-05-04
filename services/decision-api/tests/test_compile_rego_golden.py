"""Golden HTTP tests: POST /v1/rules/visual/compile/rego matches tarka_core Rego output."""

import pytest
from httpx import ASGITransport, AsyncClient

from decision_api.main import app


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _golden_aml_geo_amount() -> str:
    return (
        'package tarka.visual\n\nimport rego.v1\n\nrules contains "aml_geo_amount" if {\n'
        '    ((input.transaction.amount > 5000 and input.customer.kyc_tier == "basic") and '
        '(input.transaction.country in {"KP", "IR", "SY"} or input.risk.score >= 0.85))\n}\n'
    )


def _golden_numeric_membership() -> str:
    return (
        "package tarka.visual\n\nimport rego.v1\n\nrules contains \"numeric_membership\" if {\n"
        "    (input.channel in {1, 2, 3} and not (input.flags in {7, 8}))\n}\n"
    )


def _golden_or_of_pairs() -> str:
    return (
        "package tarka.visual\n\nimport rego.v1\n\nrules contains \"or_of_pairs\" if {\n"
        "    ((input.a == 1 and input.b < 0) or (input.c != \"x\" and input.d <= 100))\n}\n"
    )


def _golden_mixed_cmp_in() -> str:
    return (
        'package tarka.visual\n\nimport rego.v1\n\nrules contains "mixed_cmp_in" if {\n'
        '    ((input.age >= 18 and input.age <= 65 and not (input.state in {"DE", "NY"})) and '
        'input.product in {"card", "wire"})\n}\n'
    )


def _golden_precedence_mix() -> str:
    return (
        "package tarka.visual\n\nimport rego.v1\n\nrules contains \"precedence_mix\" if {\n"
        "    ((input.u.mfa == true and (input.u.ip_country == \"US\" or input.u.vpn == false)) or "
        "input.u.override == true)\n}\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected_rego",
    [
        (
            {
                "name": "m1",
                "rules": [
                    {
                        "id": "aml_geo_amount",
                        "all_of": [
                            {"field": "transaction.amount", "op": ">", "value": 5000},
                            {"field": "customer.kyc_tier", "op": "==", "value": "basic"},
                        ],
                        "any_of": [
                            {"field": "transaction.country", "op": "in", "value": ["KP", "IR", "SY"]},
                            {"field": "risk.score", "op": ">=", "value": 0.85},
                        ],
                    }
                ],
                "tag_rules": [],
            },
            _golden_aml_geo_amount(),
        ),
        (
            {
                "name": "m2",
                "rules": [
                    {
                        "id": "numeric_membership",
                        "all_of": [
                            {
                                "all_of": [
                                    {"field": "channel", "op": "in", "value": [1, 2, 3]},
                                    {"field": "flags", "op": "not in", "value": [7, 8]},
                                ]
                            }
                        ],
                        "any_of": [],
                    }
                ],
                "tag_rules": [],
            },
            _golden_numeric_membership(),
        ),
        (
            {
                "name": "m3",
                "rules": [
                    {
                        "id": "or_of_pairs",
                        "all_of": [],
                        "any_of": [
                            {
                                "all_of": [
                                    {"field": "a", "op": "==", "value": 1},
                                    {"field": "b", "op": "<", "value": 0},
                                ]
                            },
                            {
                                "all_of": [
                                    {"field": "c", "op": "!=", "value": "x"},
                                    {"field": "d", "op": "<=", "value": 100},
                                ]
                            },
                        ],
                    }
                ],
                "tag_rules": [],
            },
            _golden_or_of_pairs(),
        ),
        (
            {
                "name": "m4",
                "rules": [
                    {
                        "id": "mixed_cmp_in",
                        "all_of": [
                            {"field": "input.age", "op": ">=", "value": 18},
                            {"field": "input.age", "op": "<=", "value": 65},
                            {"field": "state", "op": "NOT IN", "value": ["DE", "NY"]},
                        ],
                        "any_of": [{"field": "product", "op": "in", "value": ["card", "wire"]}],
                    }
                ],
                "tag_rules": [],
            },
            _golden_mixed_cmp_in(),
        ),
        (
            {
                "name": "m5",
                "rules": [
                    {
                        "id": "precedence_mix",
                        "all_of": [],
                        "any_of": [
                            {
                                "all_of": [
                                    {"field": "u.mfa", "op": "==", "value": True},
                                    {
                                        "any_of": [
                                            {"field": "u.ip_country", "op": "==", "value": "US"},
                                            {"field": "u.vpn", "op": "==", "value": False},
                                        ]
                                    },
                                ]
                            },
                            {"field": "u.override", "op": "==", "value": True},
                        ],
                    }
                ],
                "tag_rules": [],
            },
            _golden_precedence_mix(),
        ),
    ],
)
async def test_compile_rego_golden_modules(
    asgi_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    expected_rego: str,
) -> None:
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    r = await asgi_client.post(
        "/v1/rules/visual/compile/rego",
        headers={"x-api-key": "k"},
        json=payload,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["package"] == "tarka.visual"
    assert body["rego_module"] == expected_rego


@pytest.mark.asyncio
async def test_compile_json_rejects_nested_ast(
    asgi_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    payload = {
        "name": "nested_only",
        "rules": [
            {
                "id": "r1",
                "all_of": [{"all_of": [{"field": "a", "op": "eq", "value": 1}]}],
                "any_of": [],
            }
        ],
        "tag_rules": [],
    }
    r = await asgi_client.post(
        "/v1/rules/visual/compile",
        headers={"x-api-key": "k"},
        json=payload,
    )
    assert r.status_code == 400
    assert "json_compile_requires_flat_leaves" in r.json()["detail"]
