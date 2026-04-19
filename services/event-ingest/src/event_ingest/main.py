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
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

import httpx
import nats
import redis.asyncio as aioredis
from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import BaseModel, Field, ValidationError

from event_ingest.config import settings
from event_ingest.ingest_contract import IngestContractError, parse_batch_event_item, parse_ingest_event_body

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

_contract_reject_reason_counts: defaultdict[str, int] = defaultdict(int)

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


def _record_contract_reject(reason_codes: list[str]) -> None:
    for code in reason_codes:
        _contract_reject_reason_counts[code] += 1
    try:
        m = get_metrics()
        m.inc("ingest_contract_reject_total")
        for code in reason_codes:
            m.inc(f"ingest_contract_reject_total_{code}")
    except Exception:
        pass


async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


async def _publish_evaluate_dlq(
    js: JetStreamContext,
    *,
    nats_subject: str,
    raw_event: dict[str, Any],
    eval_body: dict[str, Any],
    status_code: int,
    response_text: str,
) -> None:
    """Publish a structured envelope to the DLQ subject (JetStream must cover the subject)."""
    subj = settings.ingest_dlq_subject.strip()
    if not subj:
        return
    preview = response_text[:8192] if response_text else ""
    envelope: dict[str, Any] = {
        "schema_version": "1",
        "kind": "evaluate_4xx",
        "status_code": status_code,
        "nats_source_subject": nats_subject,
        "event": raw_event,
        "evaluate_request": eval_body,
        "evaluate_response_preview": preview,
    }
    await js.publish(subj, json.dumps(envelope, default=str).encode())


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
                        if settings.ingest_dlq_publish_on_evaluate_4xx and settings.ingest_dlq_subject.strip():
                            try:
                                await _publish_evaluate_dlq(
                                    js,
                                    nats_subject=getattr(msg, "subject", "") or "",
                                    raw_event=payload,
                                    eval_body=eval_body,
                                    status_code=r.status_code,
                                    response_text=r.text,
                                )
                                m.inc("ingest_dlq_published_total")
                            except Exception as e:
                                log.warning("ingest DLQ publish failed: %s", e)
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
    """Each item may be a legacy flat object or an envelope ``{schema_version, event}``."""

    events: list[dict[str, Any]]
    idempotency_key: str | None = Field(
        default=None,
        description="Optional; same as Idempotency-Key header for whole-batch deduplication",
    )


def _batch_idempotency_redis_key(idempotency_key: str, events: list[dict[str, Any]]) -> str:
    canon = json.dumps(events, sort_keys=True)
    digest = hashlib.sha256(f"{idempotency_key}\n{canon}".encode("utf-8")).hexdigest()
    return f"{settings.idempotency_key_prefix}:batch:{digest}"


@app.get("/v1/ingest/stats", dependencies=[Depends(require_api_key)])
async def ingest_stats():
    """
    In-process ingest observability (v1.2.5 E4.2).

    **contract_reject_by_reason** counts HTTP **422** contract violations since process boot
    (envelope mode, idempotency requirements, unknown ``event_type``, empty ids).
    """
    by_reason = {k: v for k, v in sorted(_contract_reject_reason_counts.items())}
    total = sum(by_reason.values())
    return {
        "service": "event-ingest",
        "since": "process_boot",
        "contract_reject_by_reason": by_reason,
        "total_contract_rejects": total,
        "envelope_mode": settings.ingest_envelope_mode,
        "require_idempotency_key": settings.ingest_require_idempotency_key,
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


@app.get("/v1/slo")
async def slo_status(request: Request):
    m = get_metrics()
    cur = m.request_count_summary()
    r = getattr(request.app.state, "redis", None)
    redis_configured = r is not None
    by_reason = {k: v for k, v in sorted(_contract_reject_reason_counts.items())}
    total_rejects = sum(by_reason.values())
    return {
        "service": "event-ingest",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 200,
        "error_budget_window_days": 30,
        "targets_note": "See docs/docs/guides/service-slos-v1.md; queue lag uses Prometheus ingest_consumer_* metrics.",
        "current": {
            **cur,
            "nats_connected": _nc is not None and getattr(_nc, "is_connected", False),
            "redis_configured": redis_configured,
            "total_contract_rejects": total_rejects,
        },
    }


@app.post("/v1/events", dependencies=[Depends(require_api_key)])
async def ingest_event(request: Request):
    """Publish a single event to NATS for async processing."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
    try:
        raw = await request.json()
    except json.JSONDecodeError:
        _record_contract_reject(["ingest_json_invalid"])
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_contract_violation", "reason_codes": ["ingest_json_invalid"]},
        ) from None
    if not isinstance(raw, dict):
        _record_contract_reject(["ingest_body_not_object"])
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_contract_violation", "reason_codes": ["ingest_body_not_object"]},
        )

    try:
        flat = parse_ingest_event_body(raw, envelope_mode=settings.ingest_envelope_mode)
        body = EventPayload.model_validate(flat)
    except IngestContractError as e:
        _record_contract_reject(e.reason_codes)
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_contract_violation", "reason_codes": e.reason_codes, "message": e.message},
        ) from e
    except ValidationError as e:
        _record_contract_reject(["ingest_model_validation"])
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ingest_contract_violation",
                "reason_codes": ["ingest_model_validation"],
                "detail": e.errors(include_url=False),
            },
        ) from e

    redis = getattr(request.app.state, "redis", None)
    idem_header = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    if settings.ingest_require_idempotency_key and not (idem_header or "").strip():
        raise _ingest_contract_http_exception("ingest_idempotency_key_required")

    try:
        inner = parse_ingest_body(body, envelope_mode=settings.ingest_envelope_mode)
    except ValueError as e:
        code = str(e.args[0]) if e.args else "ingest_event_invalid"
        raise _ingest_contract_http_exception(code) from None

    body_model = EventPayload.model_validate(inner.model_dump(mode="json"))
    redis = getattr(request.app.state, "redis", None)
    idem_meta = (body_model.metadata or {}).get("idempotency_key") if isinstance(body_model.metadata, dict) else None
    idem = (idem_header or idem_meta or "").strip() or None

    if settings.ingest_require_idempotency_key and not idem:
        _record_contract_reject(["ingest_idempotency_key_required"])
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ingest_contract_violation",
                "reason_codes": ["ingest_idempotency_key_required"],
            },
        )

    if redis is not None and idem:
        rkey = _idempotency_redis_key(body_model.tenant_id, idem)
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

    subject = f"{settings.subject_prefix}.{body_model.tenant_id}.{body_model.event_type}"
    data = body_model.model_dump(mode="json")
    data["_ingest_id"] = uuid.uuid4().hex
    ack = await _js.publish(subject, json.dumps(data).encode())
    try:
        get_metrics().inc("events_ingested_total")
    except Exception:
        pass
    response = {"accepted": True, "stream_seq": ack.seq, "ingest_id": data["_ingest_id"]}
    if redis is not None and idem:
        rkey = _idempotency_redis_key(body_model.tenant_id, idem)
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
async def ingest_batch(request: Request):
    """Publish a batch of events."""
    if not _js:
        raise HTTPException(503, "NATS not connected")
    try:
        raw = await request.json()
    except json.JSONDecodeError:
        _record_contract_reject(["ingest_json_invalid"])
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_contract_violation", "reason_codes": ["ingest_json_invalid"]},
        ) from None
    if not isinstance(raw, dict):
        _record_contract_reject(["ingest_body_not_object"])
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_contract_violation", "reason_codes": ["ingest_body_not_object"]},
        )

    events_in = raw.get("events")
    if not isinstance(events_in, list):
        _record_contract_reject(["ingest_batch_events_not_array"])
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_contract_violation", "reason_codes": ["ingest_batch_events_not_array"]},
        )

    parsed_events: list[EventPayload] = []
    for item in events_in:
        if not isinstance(item, dict):
            _record_contract_reject(["ingest_batch_item_not_object"])
            raise HTTPException(
                status_code=422,
                detail={"error": "ingest_contract_violation", "reason_codes": ["ingest_batch_item_not_object"]},
            )
        try:
            flat = parse_batch_event_item(item, envelope_mode=settings.ingest_envelope_mode)
            parsed_events.append(EventPayload.model_validate(flat))
        except IngestContractError as e:
            _record_contract_reject(e.reason_codes)
            raise HTTPException(
                status_code=422,
                detail={"error": "ingest_contract_violation", "reason_codes": e.reason_codes, "message": e.message},
            ) from e
        except ValidationError as e:
            _record_contract_reject(["ingest_model_validation"])
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "ingest_contract_violation",
                    "reason_codes": ["ingest_model_validation"],
                    "detail": e.errors(include_url=False),
                },
            ) from e

    idem_body = raw.get("idempotency_key")
    idem_body_s = (idem_body.strip() if isinstance(idem_body, str) else None) or None
    body = BatchPayload(events=parsed_events, idempotency_key=idem_body_s)

    redis = getattr(request.app.state, "redis", None)
    idem_header = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    idem = (idem_header or idem_body_s or "").strip() or None

    if settings.ingest_require_idempotency_key and not idem:
        _record_contract_reject(["ingest_idempotency_key_required"])
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ingest_contract_violation",
                "reason_codes": ["ingest_idempotency_key_required"],
            },
        )

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
    for raw_ev in body.events:
        if not isinstance(raw_ev, dict):
            raise _ingest_contract_http_exception("ingest_body_not_object")
        try:
            inner = parse_ingest_body(raw_ev, envelope_mode=settings.ingest_envelope_mode)
        except ValueError as e:
            code = str(e.args[0]) if e.args else "ingest_event_invalid"
            raise _ingest_contract_http_exception(code) from None
        event = EventPayload.model_validate(inner.model_dump(mode="json"))
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
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if not allow:
            await ws.close(code=1011, reason="service auth misconfigured: API_KEYS is empty")
            return
    elif ws.headers.get("x-api-key", "") not in keys:
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
                if not isinstance(parsed, dict):
                    _record_contract_reject(["ingest_body_not_object"])
                    await ws.send_json({"error": "ingest_contract_violation", "reason_codes": ["ingest_body_not_object"]})
                    continue
                try:
                    flat = parse_ingest_event_body(parsed, envelope_mode=settings.ingest_envelope_mode)
                    ep = EventPayload.model_validate(flat)
                except IngestContractError as e:
                    _record_contract_reject(e.reason_codes)
                    await ws.send_json(
                        {
                            "error": "ingest_contract_violation",
                            "reason_codes": e.reason_codes,
                            "message": e.message,
                        }
                    )
                    continue
                except ValidationError as e:
                    _record_contract_reject(["ingest_model_validation"])
                    await ws.send_json(
                        {
                            "error": "ingest_contract_violation",
                            "reason_codes": ["ingest_model_validation"],
                            "detail": e.errors(include_url=False),
                        }
                    )
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
