"""High-throughput event ingestion service.

Accepts events via REST or WebSocket, publishes to NATS JetStream.
A built-in consumer drains NATS and forwards to Decision API.
"""
import asyncio
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
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import BaseModel, Field

from event_ingest.config import settings

_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from observability import setup_observability, get_metrics  # noqa: E402

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
            max_age=86400 * 7 * 1_000_000_000,  # 7 days in nanoseconds
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
                try:
                    payload = json.loads(msg.data.decode())
                    url = f"{settings.decision_api_url.rstrip('/')}/v1/decisions/evaluate"
                    r = await http.post(url, json=payload, timeout=10.0)
                    if r.status_code < 500:
                        await msg.ack()
                    else:
                        await msg.nak(delay=5)
                except Exception as e:
                    log.warning("consumer error: %s", e)
                    try:
                        await msg.nak(delay=5)
                    except Exception:
                        pass
        except nats.errors.TimeoutError:
            await asyncio.sleep(0.05)
        except Exception as e:
            log.error("consumer loop error: %s", e)
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _nc, _js
    _nc, _js = await _connect_nats()
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
    if _nc:
        await _nc.drain()


app = FastAPI(
    title="Tarka Event Ingest",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
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


@app.get("/v1/health")
async def health():
    return {"status": "ok", "nats_connected": _nc is not None and _nc.is_connected}


@app.post("/v1/events")
async def ingest_event(body: EventPayload):
    """Publish a single event to NATS for async processing."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
    subject = f"{settings.subject_prefix}.{body.tenant_id}.{body.event_type}"
    data = body.model_dump(mode="json")
    data["_ingest_id"] = uuid.uuid4().hex
    ack = await _js.publish(subject, json.dumps(data).encode())
    try:
        get_metrics().inc("events_ingested_total")
    except Exception:
        pass
    return {"accepted": True, "stream_seq": ack.seq, "ingest_id": data["_ingest_id"]}


@app.post("/v1/events/batch")
async def ingest_batch(body: BatchPayload):
    """Publish a batch of events."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
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
    return {"accepted": len(results), "results": results}


@app.websocket("/v1/events/ws")
async def ws_ingest(ws: WebSocket):
    """WebSocket endpoint for continuous event streaming."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                if not _js:
                    await ws.send_json({"error": "NATS not connected"})
                    continue
                tenant = data.get("tenant_id", "unknown")
                etype = data.get("event_type", "custom")
                subject = f"{settings.subject_prefix}.{tenant}.{etype}"
                data["_ingest_id"] = uuid.uuid4().hex
                ack = await _js.publish(subject, json.dumps(data).encode())
                await ws.send_json({"accepted": True, "seq": ack.seq, "ingest_id": data["_ingest_id"]})
            except json.JSONDecodeError:
                await ws.send_json({"error": "invalid JSON"})
    except WebSocketDisconnect:
        pass


@app.get("/v1/stream/info")
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
