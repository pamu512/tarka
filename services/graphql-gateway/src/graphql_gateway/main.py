from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from observability import setup_observability  # noqa: E402
from strawberry.fastapi import GraphQLRouter

from graphql_gateway.config import settings
from graphql_gateway.schema import schema

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_valid_api_keys: frozenset[str] | None = None


def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = settings.api_keys.strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys


async def _require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        allow = settings.allow_insecure_no_auth
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


async def get_context(request: Request) -> dict:
    await _require_api_key(request)
    return {"http_client": request.app.state.http_client}


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout, connect=settings.http_connect_timeout),
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive,
        ),
    )
    yield
    await application.state.http_client.aclose()


graphql_router = GraphQLRouter(schema, context_getter=get_context)

app = FastAPI(
    title="Tarka GraphQL Gateway",
    version="1.0.0",
    lifespan=lifespan,
)
setup_observability(app, "graphql-gateway")
app.include_router(graphql_router, prefix="/graphql")


@app.get("/v1/health")
async def health():
    return {"status": "ok"}
