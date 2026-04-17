"""High-throughput event ingestion service.

Accepts events via REST or WebSocket, publishes to NATS JetStream.
A built-in consumer drains NATS and forwards to Decision API.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
import nats
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import BaseModel, Field, ValidationError

from event_ingest.config import settings

# Keys added by ingest; must not be forwarded to Decision API evaluate.
_INGEST_INTERNAL_KEYS = frozenset({"_ingest_id"})


def _payload_for_decision_api(msg: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in msg.items() if k not in _INGEST_INTERNAL_KEYS}


def _idempotency_redis_key(tenant_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{settings.idempotency_key_prefix}:{tenant_id}:{digest}"


_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from observability import get_metrics, setup_observability  # noqa: E402

log = logging.getLogger("event-ingest")

_nc: NatsClient | None = None
_js: JetStreamContext | None = None

# ---------- auth ----------
_valid_api_keys: frozenset[str] | None = None


def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = settings.api_keys.strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys


async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        return
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


async def _connect_nats() -> tuple[NatsClient, JetStreamContext]:
    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()
    try:
        await js.find_stream_name_by_subject(f"{settings.subject_prefix}.>")
    except Exception:
        await js.add_stream(
            name=settings.stream_name,
            subjects=[f"{settings.subject_prefix}.>"],
            retention="limits",
            max_msgs=10_000_000,
            max_bytes=1024 * 1024 * 1024,
        )
    return nc, js


async def _consumer_loop(js: JetStreamContext, http: httpx.AsyncClient) -> None:
    """Pull events from NATS and forward to Decision API."""
    sub = await js.pull_subscribe(
        f"{settings.subject_prefix}.>",
        durable="decision-worker",
        stream=settings.stream_name,
    )
    while True:
        try:
            msgs = await sub.fetch(batch=settings.max_batch_size, timeout=1)
            for msg in msgs:
                m = get_metrics()
                try:
                    try:
                        payload = json.loads(msg.data.decode())
                    except json.JSONDecodeError:
                        m.inc("ingest_consumer_json_decode_errors_total")
                        await msg.nak(delay=5)
                        continue
                    url = f"{settings.decision_api_url.rstrip('/')}/v1/decisions/evaluate"
                    eval_body = _payload_for_decision_api(payload)
                    r = await http.post(url, json=eval_body, timeout=10.0)
                    if r.status_code < 400:
                        m.inc("ingest_consumer_evaluate_2xx_total")
                        await msg.ack()
                        m.inc("ingest_consumer_nats_ack_total")
                    elif r.status_code < 500:
                        m.inc("ingest_consumer_evaluate_4xx_total")
                        await msg.ack()
                        m.inc("ingest_consumer_nats_ack_total")
                    else:
                        m.inc("ingest_consumer_evaluate_5xx_total")
                        await msg.nak(delay=5)
                        m.inc("ingest_consumer_nats_nak_total")
                except Exception as e:
                    log.warning("consumer error: %s", e)
                    try:
                        m.inc("ingest_consumer_nats_nak_total")
                        await msg.nak(delay=5)
                    except Exception:
                        pass
        except nats.errors.TimeoutError:
            await asyncio.sleep(0.05)
        except Exception as e:
            log.error("consumer loop error: %s", e)
            await asyncio.sleep(1)


async def _connect_redis() -> aioredis.Redis | None:
    raw = settings.redis_url.strip()
    if not raw:
        return None
    r = aioredis.from_url(raw, decode_responses=True)
    await r.ping()
    return r


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _nc, _js
    _nc, _js = await _connect_nats()
    redis_client = await _connect_redis()
    application.state.redis = redis_client
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=3.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    application.state.http = http
    consumer_coro = _consumer_loop(_js, http)
    consumer_task = asyncio.create_task(consumer_coro)
    if not isinstance(consumer_task, asyncio.Task) and inspect.iscoroutine(consumer_coro):
        # Test suites may mock create_task; close unscheduled coroutine to avoid leaks.
        consumer_coro.close()
    yield
    consumer_task.cancel()
    try:
        if inspect.isawaitable(consumer_task):
            await consumer_task
    except asyncio.CancelledError:
        pass
    await http.aclose()
    if application.state.redis is not None:
        await application.state.redis.aclose()
        application.state.redis = None
    if _nc:
        await _nc.drain()


app = FastAPI(
    title="Tarka Event Ingest",
    version="1.0.0",
    lifespan=lifespan,
)
setup_observability(app, "event-ingest")


class EventPayload(BaseModel):
    tenant_id: str
    event_type: str
    entity_id: str
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    device_context: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchPayload(BaseModel):
    events: list[EventPayload]
    idempotency_key: str | None = Field(
        default=None,
        description="Optional; same as Idempotency-Key header for whole-batch deduplication",
    )


def _batch_idempotency_redis_key(idempotency_key: str, events: list[EventPayload]) -> str:
    canon = json.dumps(
        [e.model_dump(mode="json", exclude_none=True) for e in events],
        sort_keys=True,
    )
    digest = hashlib.sha256(f"{idempotency_key}\n{canon}".encode("utf-8")).hexdigest()
    return f"{settings.idempotency_key_prefix}:batch:{digest}"


@app.get("/v1/ingest/stats", dependencies=[Depends(require_api_key)])
async def ingest_stats():
    """
    In-process ingest observability (v1.2.5 E4.2).

    **contract_reject_by_reason** increments when contract-first validation rejects a body
    (envelope mode, idempotency requirements, unknown event types). Until that path is active,
    counts stay at zero — the field is still returned for UI wiring.
    """
    return {
        "service": "event-ingest",
        "since": "process_boot",
        "contract_reject_by_reason": {},
        "total_contract_rejects": 0,
        "note": "Reject counters populate when contract validation is enabled on ingest paths.",
    }


@app.get("/v1/health")
async def health(request: Request):
    r = getattr(request.app.state, "redis", None)
    redis_configured = r is not None
    redis_ok: bool | None = None
    if r is not None:
        try:
            await r.ping()
            redis_ok = True
        except Exception:
            redis_ok = False
    return {
        "status": "ok",
        "nats_connected": _nc is not None and _nc.is_connected,
        "redis_configured": redis_configured,
        "redis_ok": redis_ok,
    }


@app.post("/v1/events", dependencies=[Depends(require_api_key)])
async def ingest_event(request: Request, body: EventPayload):
    """Publish a single event to NATS for async processing."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
    redis = getattr(request.app.state, "redis", None)
    idem_header = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    idem_meta = (body.metadata or {}).get("idempotency_key") if isinstance(body.metadata, dict) else None
    idem = (idem_header or idem_meta or "").strip() or None

    if redis is not None and idem:
        rkey = _idempotency_redis_key(body.tenant_id, idem)
        try:
            cached = await redis.get(rkey)
        except Exception as e:
            log.warning("idempotency redis get failed: %s", e)
            cached = None
        if cached:
            try:
                out = json.loads(cached)
            except json.JSONDecodeError:
                out = None
            if isinstance(out, dict) and "ingest_id" in out:
                out = {**out, "duplicate": True}
                try:
                    get_metrics().inc("ingest_idempotent_hits_total")
                except Exception:
                    pass
                return out

    subject = f"{settings.subject_prefix}.{body.tenant_id}.{body.event_type}"
    data = body.model_dump(mode="json")
    data["_ingest_id"] = uuid.uuid4().hex
    ack = await _js.publish(subject, json.dumps(data).encode())
    try:
        get_metrics().inc("events_ingested_total")
    except Exception:
        pass
    response = {"accepted": True, "stream_seq": ack.seq, "ingest_id": data["_ingest_id"]}
    if redis is not None and idem:
        rkey = _idempotency_redis_key(body.tenant_id, idem)
        try:
            await redis.set(
                rkey,
                json.dumps(response),
                ex=settings.idempotency_ttl_seconds,
            )
        except Exception as e:
            log.warning("idempotency redis set failed: %s", e)
    return response


@app.post("/v1/events/batch", dependencies=[Depends(require_api_key)])
async def ingest_batch(request: Request, body: BatchPayload):
    """Publish a batch of events."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
    redis = getattr(request.app.state, "redis", None)
    idem_header = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    idem_body = (body.idempotency_key or "").strip() or None
    idem = (idem_header or idem_body or "").strip() or None

    if redis is not None and idem:
        bkey = _batch_idempotency_redis_key(idem, body.events)
        try:
            cached = await redis.get(bkey)
        except Exception as e:
            log.warning("batch idempotency redis get failed: %s", e)
            cached = None
        if cached:
            try:
                out = json.loads(cached)
            except json.JSONDecodeError:
                out = None
            if isinstance(out, dict) and "results" in out:
                out = {**out, "duplicate": True}
                try:
                    get_metrics().inc("ingest_idempotent_hits_total")
                except Exception:
                    pass
                return out

    results = []
    for event in body.events:
        subject = f"{settings.subject_prefix}.{event.tenant_id}.{event.event_type}"
        data = event.model_dump(mode="json")
        data["_ingest_id"] = uuid.uuid4().hex
        ack = await _js.publish(subject, json.dumps(data).encode())
        results.append({"ingest_id": data["_ingest_id"], "seq": ack.seq})
    try:
        get_metrics().inc("events_ingested_total", len(body.events))
    except Exception:
        pass
    response = {"accepted": len(results), "results": results}
    if redis is not None and idem:
        bkey = _batch_idempotency_redis_key(idem, body.events)
        try:
            await redis.set(
                bkey,
                json.dumps(response),
                ex=settings.idempotency_ttl_seconds,
            )
        except Exception as e:
            log.warning("batch idempotency redis set failed: %s", e)
    return response


@app.websocket("/v1/events/ws")
async def ws_ingest(ws: WebSocket):
    """WebSocket endpoint for continuous event streaming."""
    keys = _get_api_keys()
    if keys and ws.headers.get("x-api-key", "") not in keys:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                parsed = json.loads(raw)
                if not _js:
                    await ws.send_json({"error": "NATS not connected"})
                    continue
                try:
                    ep = EventPayload.model_validate(parsed)
                except ValidationError as e:
                    await ws.send_json({"error": "validation_error", "detail": e.errors(include_url=False)})
                    continue
                data = ep.model_dump(mode="json")
                data["_ingest_id"] = uuid.uuid4().hex
                subject = f"{settings.subject_prefix}.{data['tenant_id']}.{data['event_type']}"
                ack = await _js.publish(subject, json.dumps(data).encode())
                await ws.send_json({"accepted": True, "seq": ack.seq, "ingest_id": data["_ingest_id"]})
            except json.JSONDecodeError:
                await ws.send_json({"error": "invalid JSON"})
    except WebSocketDisconnect:
        pass


@app.get("/v1/stream/info", dependencies=[Depends(require_api_key)])
async def stream_info():
    """Return NATS stream metadata."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
    info = await _js.find_stream_name_by_subject(f"{settings.subject_prefix}.>")
    stream = await _js.stream_info(info)
    return {
        "stream": stream.config.name,
        "messages": stream.state.messages,
        "bytes": stream.state.bytes,
        "first_seq": stream.state.first_seq,
        "last_seq": stream.state.last_seq,
        "consumer_count": stream.state.consumer_count,
    }
