"""HTTP-level tests for :class:`~adapters.biometrics.incognia.client.IncogniaClient` using ``httpx.MockTransport``."""

from __future__ import annotations

import json
import unittest

import httpx

from adapters.biometrics.incognia.client import IncogniaClient, IncogniaClientSettings
from adapters.biometrics.incognia.schemas import PostFeedbackRequestBody, PostSignupRequestBody, PostTransactionRequestBody


def _signup_body() -> dict:
    return {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "requestId": "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff",
        "riskAssessment": "low_risk",
        "reasons": [{"code": "trusted_network", "source": "incognia"}],
        "actions": [],
        "deviceId": "dev",
        "installationId": "inst",
    }


def _transaction_body() -> dict:
    return {
        "id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        "riskAssessment": "high_risk",
        "reasons": [],
        "actions": [],
        "installationId": "inst2",
    }


def _make_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/v2/token"):
            assert request.headers.get("authorization", "").startswith("Basic ")
            assert b"grant_type=client_credentials" in request.content
            payload = {
                "accessToken": "tok-test",
                "expiresIn": 3600,
                "tokenType": "Bearer",
            }
            return httpx.Response(200, json=payload)
        if path.endswith("/api/v2/onboarding/signups"):
            auth = request.headers.get("authorization")
            assert auth == "Bearer tok-test"
            return httpx.Response(200, json=_signup_body())
        if path.endswith("/api/v2/authentication/transactions"):
            assert request.headers.get("authorization") == "Bearer tok-test"
            q = str(request.url.query)
            assert "eval=true" in q or "eval=false" in q or q == ""
            return httpx.Response(200, json=_transaction_body())
        if path.endswith("/api/v2/feedbacks"):
            assert request.headers.get("authorization") == "Bearer tok-test"
            body = json.loads(request.content.decode())
            assert body.get("event") == "login_accepted"
            assert "dry_run=false" in str(request.url) or "dry_run=true" in str(request.url)
            return httpx.Response(200, json={})
        return httpx.Response(404, text="unexpected path " + path)

    return httpx.MockTransport(handler)


class IncogniaClientMockTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_signup_flow(self) -> None:
        settings = IncogniaClientSettings(
            client_id="id",
            client_secret="secret",
            api_base_url="https://api.incognia.com",
            max_retries=2,
            circuit_failure_threshold=50,
        )
        async with IncogniaClient(settings, http_client=httpx.AsyncClient(transport=_make_transport())) as client:
            out = await client.post_signup(PostSignupRequestBody(requestToken="rt"))
            assert str(out.id) == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            assert out.riskAssessment == "low_risk"

    async def test_post_transaction_eval_query(self) -> None:
        settings = IncogniaClientSettings(
            client_id="id",
            client_secret="secret",
            api_base_url="https://api.incognia.com",
            max_retries=2,
            circuit_failure_threshold=50,
        )
        transport = _make_transport()

        async with IncogniaClient(settings, http_client=httpx.AsyncClient(transport=transport)) as client:
            tx = PostTransactionRequestBody(accountId="acc", type="login")
            ass = await client.post_transaction(tx, evaluate_transaction=True)
            assert ass.riskAssessment == "high_risk"

    async def test_post_feedback_dry_run_false(self) -> None:
        settings = IncogniaClientSettings(
            client_id="id",
            client_secret="secret",
            api_base_url="https://api.incognia.com",
            max_retries=2,
            circuit_failure_threshold=50,
        )

        def feedback_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/v2/token"):
                return httpx.Response(
                    200,
                    json={"accessToken": "t2", "expiresIn": 3600, "tokenType": "Bearer"},
                )
            if request.url.path.endswith("/api/v2/feedbacks"):
                assert "dry_run=false" in str(request.url)
                return httpx.Response(200, json={})
            return httpx.Response(404)

        async with IncogniaClient(
            settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(feedback_handler)),
        ) as client:
            await client.post_feedback(
                PostFeedbackRequestBody(event="login_accepted", timestamp=1_700_000_000_000),
                dry_run=False,
            )


if __name__ == "__main__":
    unittest.main()
