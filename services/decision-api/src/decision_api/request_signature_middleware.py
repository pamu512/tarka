from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

"""Optional HMAC verification for POST bodies (see docs/guides/tls-pinning-and-signed-requests.md)."""
# Shared helpers (repo layout: services/shared next to decision-api)
_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from tarka_request_signature import verify_signature  # noqa: E402


class RequestSignatureMiddleware(BaseHTTPMiddleware):
    """When ``secret`` is set, require valid ``X-Tarka-*`` headers on configured paths."""

    def __init__(
        self,
        app,
        *,
        secret: str,
        path_prefixes: tuple[str, ...] = ("/v1/decisions/evaluate",),
        max_skew_seconds: int = 300,
    ) -> None:
        super().__init__(app)
        self._secret = secret
        self._path_prefixes = path_prefixes
        self._max_skew = max_skew_seconds

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method != "POST" or not self._secret:
            return await call_next(request)
        path = request.url.path
        if not any(path == p or path.startswith(p + "/") for p in self._path_prefixes):
            return await call_next(request)

        body = await request.body()
        hdrs = {k: v for k, v in request.headers.items()}
        if not verify_signature(
            body, hdrs, secret=self._secret, max_skew_seconds=self._max_skew
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid or missing request signature"},
            )

        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
        return await call_next(request)
