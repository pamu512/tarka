"""Issue server-bound ``session_nonce`` values for client in-transit integrity (Redis)."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from signal_api.transit_integrity import redis_ingest_nonce_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Session"])


class SessionNonceIssueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID | None = Field(
        default=None,
        description="Optional; when omitted a new session UUID is minted.",
    )


class SessionNonceIssueResponse(BaseModel):
    session_id: UUID
    nonce: str


def _nonce_ttl_sec() -> int:
    raw = os.environ.get("SIGNAL_SESSION_NONCE_TTL_SEC", "").strip()
    if not raw:
        return 86_400
    return max(300, min(int(raw), 86_400 * 7))


async def get_redis(request: Request) -> Redis:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "redis_unavailable"},
        )
    return r


@router.post(
    "/nonce",
    response_model=SessionNonceIssueResponse,
    summary="Mint session id + nonce for page-load integrity hashing",
)
async def issue_session_nonce(
    body: SessionNonceIssueBody,
    redis: Annotated[Redis, Depends(get_redis)],
) -> SessionNonceIssueResponse:
    sid = body.session_id or uuid4()
    nonce = secrets.token_urlsafe(32)
    key = redis_ingest_nonce_key(str(sid))
    ttl = _nonce_ttl_sec()
    await redis.set(key, nonce, ex=ttl)
    logger.info("session_nonce_issued session_id=%s", sid)
    return SessionNonceIssueResponse(session_id=sid, nonce=nonce)
