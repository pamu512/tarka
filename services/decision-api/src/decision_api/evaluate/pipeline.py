"""Evaluate pipeline — sync decision path body (HTTP shell stays in main)."""

from __future__ import annotations

import asyncio
import hashlib
import json as _json
import os
import uuid
from typing import Any

from fastapi import BackgroundTasks, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.async_osint_redis import (
    merge_cached_async_osint,
    publish_async_enrichment_request,
)
from decision_api.challenge_policy import apply_challenge_policy
from decision_api.config import settings
from decision_api.consortium import consortium_score_delta, hash_entity_id
from decision_api.currency import normalize_amount
from decision_api.decision_log import build_decision_log_record, emit_decision_log
from decision_api.device_scoring import extract_device_entropy_tags
from decision_api.enforcement import resolve_enforcement_action
from decision_api.eval_dag import EvalDAGRuntime
from decision_api.eval_load_guard import acquire_eval_capacity
from decision_api.eval_steps import run_evaluation_step
from decision_api.evaluate.score import (
    blend_scores as _blend_scores,
    compute_fallback_reason as _compute_fallback_reason,
    decision_runtime_status as _decision_runtime_status,
    signal_availability_notes_from_tags as _signal_availability_notes_from_tags,
)
from decision_api.graph_decision_explanation import build_graph_decision_explanation_v1
from decision_api.graph_intel import graph_score_delta, graph_tags_from_risk
from decision_api.inference_build import (
    build_inference_context,
    derive_recommended_action,
)
from decision_api.integrity_policy import (
    apply_evaluate_integrity_tags,
    supplemental_tags_for_integrity,
)
from decision_api.location_cohort_evidence import build_location_cohort_evidence
from decision_api.relatedness_evidence import build_relatedness_evidence
from decision_api.location_context import merge_session_geo_from_device_and_features
from decision_api.models import AuditRecord
from decision_api.policy_routing import (
    build_canary_cohort_audit,
    build_policy_routing_audit,
    cohort_bucket_0_99,
    decision_from_rule_score,
)
from decision_api.schemas import EvaluateRequest, EvaluateResponse
from decision_api.tags import derive_contextual_tags
from decision_api.typology import evaluate_typologies, summarize_typologies
from event_time import event_time_unix_for_evaluate
from privacy import get_profile, mask_dict

# Bound after main finishes loading (avoids circular import at module import time).
_m: Any = None


def bind_main(module: Any) -> None:
    """Wire main-module helpers used by the evaluate body."""
    global _m
    _m = module


def _require_main() -> Any:
    if _m is None:
        raise RuntimeError("evaluate pipeline not bound to decision_api.main")
    return _m


async def run_evaluate_decision(
    body: EvaluateRequest,
    request: Request,
    bg: BackgroundTasks,
    session: AsyncSession,
) -> EvaluateResponse:
    m = _require_main()
    from decision_api.evaluate_shadow_request import is_shadow_evaluate_request
    from decision_api.partner_fusion import (
        graph_writeback_hints,
        maybe_fetch_partner_signals,
        signals_to_feature_tags,
    )

    shadow_request = is_shadow_evaluate_request(body.metadata)
    # Helpers / stores that still live on the main module
    _audit_counter_version_label = m._audit_counter_version_label
    _broadcast_decision = m._broadcast_decision
    _build_artifact_manifest = m._build_artifact_manifest
    _evaluate_opa_wrapped = m._evaluate_opa_wrapped
    _feature_snapshot_fallback = m._feature_snapshot_fallback
    _fetch_calibration_adjustment_wrapped = m._fetch_calibration_adjustment_wrapped
    _fetch_counter_snapshot_wrapped = m._fetch_counter_snapshot_wrapped
    _fetch_feature_snapshot_wrapped = m._fetch_feature_snapshot_wrapped
    _fetch_graph_risk_wrapped = m._fetch_graph_risk_wrapped
    _fetch_location_evaluation_wrapped = m._fetch_location_evaluation_wrapped
    _fetch_ml_score_wrapped = m._fetch_ml_score_wrapped
    _graph_checkpoint_from_body = m._graph_checkpoint_from_body
    _graph_upsert_stepped = m._graph_upsert_stepped
    _http = m._http
    _infer_ctx_kwargs = m._infer_ctx_kwargs
    _list_check_with_circuit = m._list_check_with_circuit
    _load_tenant_flags_for_evaluate = m._load_tenant_flags_for_evaluate
    _metadata_etl_batch_id = m._metadata_etl_batch_id
    _metrics_inc_safe = m._metrics_inc_safe
    _publish_decision = m._publish_decision
    _resolve_response_explainability_tier = m._resolve_response_explainability_tier
    _run_shadow_evaluation = m._run_shadow_evaluation
    _shape_inference_context_for_tier = m._shape_inference_context_for_tier
    _upstream_headers = m._upstream_headers
    redis_tags = m.redis_tags
    entity_link_store = m.entity_link_store
    agg_store = m.agg_store
    fingerprint_store = m.fingerprint_store
    extract_signal_tags = m.extract_signal_tags
    extract_behavior_tags = m.extract_behavior_tags
    extract_captcha_tags = m.extract_captcha_tags
    decide_graph_routing = m.decide_graph_routing
    dependency_resilience_policy_table = m.dependency_resilience_policy_table
    # Prefer main-module symbol so tests that patch decision_api.main.* still apply.
    evaluate_json_rules = m.evaluate_json_rules

    if settings.evaluate_require_idempotency_key:
        idem = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("idempotency-key")
            or ""
        ).strip()
        if not idem:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "evaluate_idempotency_required",
                    "message": "Idempotency-Key header is required when TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY is enabled.",
                },
            )

    http = _http(request)
    trace_id = uuid.uuid4()
    replay_ttl_seconds = int(os.environ.get("REPLAY_PAYLOAD_TTL_SECONDS", "300"))
    degrade_tags: list[str] = []
    from decision_api.policy_set import current_policy_set_id

    policy_set_id = current_policy_set_id() or None
    tenant_flags = await _load_tenant_flags_for_evaluate(body.tenant_id)

    # Extract SDK signal tags
    dc_dump = body.device_context.model_dump() if body.device_context else None
    signal_tags = extract_signal_tags(dc_dump)
    signal_tags.extend(extract_behavior_tags(dc_dump))
    signal_tags.extend(extract_device_entropy_tags(dc_dump))
    signal_tags.extend(extract_captcha_tags(dc_dump))
    if shadow_request:
        signal_tags.append("evaluate:shadow")
    consortium_delta = 0.0
    graph_delta = 0.0
    _external_signal_delta = 0.0
    external_signal_meta: dict[str, Any] | None = None
    replay_rule_hits: list[str] = []

    # Detect payload replay at ingress using a short-lived signature cache.
    replay_signature = hashlib.sha256(
        _json.dumps(
            {
                "tenant_id": body.tenant_id,
                "event_type": body.event_type.value,
                "entity_id": body.entity_id,
                "session_id": body.session_id,
                "payload": body.payload,
                "device_id": body.device_context.device_id
                if body.device_context
                else None,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    if shadow_request:
        is_replayed = False
    else:
        is_replayed = await redis_tags.check_and_store_replay_signature(
            body.tenant_id, replay_signature, ttl_seconds=replay_ttl_seconds
        )
    if is_replayed:
        signal_tags.append("ingress:replay_payload")
        replay_rule_hits.append("ingress_replay_detected")

    hmac_ok = getattr(request.state, "tarka_request_signature_ok", None)
    if hmac_ok is not True:
        hmac_ok = None
    else:
        hmac_ok = True
    pin_raw = None
    if isinstance(body.metadata, dict) and "tls_pinning_verified" in body.metadata:
        raw_pin = body.metadata.get("tls_pinning_verified")
        if isinstance(raw_pin, bool):
            pin_raw = raw_pin
        elif isinstance(raw_pin, str):
            pin_raw = raw_pin.strip().lower() in ("1", "true", "yes", "on")
    signal_tags.extend(
        apply_evaluate_integrity_tags(
            signal_tags,
            hmac_ok=hmac_ok,
            request_signature_required=bool(settings.request_signature_secret),
            integrity_soft_tags=bool(settings.integrity_soft_tags),
            tls_pinning_verified=pin_raw,
            is_replayed=bool(is_replayed),
        )
    )

    # Record fingerprint & detect shared devices (skip writes on shadow duplicate traffic)
    if not shadow_request and body.device_context and fingerprint_store._client:
        fp_record = await fingerprint_store.record_fingerprint(
            body.tenant_id,
            body.device_context.model_dump(),
            body.entity_id,
        )
        if len(fp_record.entity_ids) > 1:
            signal_tags.append("sdk:shared_device")

    # Server-side entity ↔ device ↔ vendor ID linking (Redis)
    if not shadow_request and body.device_context and entity_link_store._client:
        dc = body.device_context
        await entity_link_store.record_device_entity_link(
            body.tenant_id,
            dc.device_id,
            body.entity_id,
        )
        if isinstance(body.metadata, dict) and body.metadata:
            await entity_link_store.record_vendor_bridge(
                body.tenant_id, body.entity_id, body.metadata
            )

    partner_evidence: list[dict[str, Any]] = []
    partner_graph_hints: dict[str, Any] | None = None
    partner_features: dict[str, Any] = {}
    if isinstance(body.metadata, dict) and (
        body.metadata.get("fingerprint_request_id")
        or body.metadata.get("incognia_account_id")
    ):
        partner_signals = await maybe_fetch_partner_signals(
            http=http,
            session=session,
            metadata=body.metadata,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            trace_id=str(trace_id),
        )
        if partner_signals:
            partner_features, p_tags, partner_evidence = signals_to_feature_tags(
                partner_signals
            )
            signal_tags.extend(p_tags)
            partner_graph_hints = graph_writeback_hints(
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                transaction_id=str(trace_id),
                tags=p_tags,
                features=partner_features,
            )

    # Check whitelist/blacklist/test bypass BEFORE full evaluation (bounded list step #32)
    list_check = None
    step_trace: list[dict[str, Any]] = []

    async def _list_check_call():
        return await _list_check_with_circuit(
            body.tenant_id, body.entity_id, degrade_tags, tenant_flags
        )

    list_check, list_trace = await run_evaluation_step(
        "list",
        _list_check_call,
        timeout_seconds=settings.eval_step_list_timeout_seconds,
        max_attempts=settings.eval_step_list_max_attempts,
        on_failure="SKIP",
        fallback=None,
    )
    step_trace.append(list_trace)

    if list_check and list_check.found:
        if list_check.action == "allow":
            _wl_inf = build_inference_context(
                [], ["whitelist_bypass"], None, 0.0, None, **_infer_ctx_kwargs(body, {})
            )
            _wl_rec, _wl_meta = apply_challenge_policy(
                body.challenge_policy_id,
                None,
                "allow",
                _wl_inf,
                ["list:whitelist"],
                body.payload,
            )
            audit = AuditRecord(
                trace_id=trace_id,
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision="allow",
                score=0.0,
                tags=["list:whitelist"],
                rule_hits=["whitelist_bypass"],
                payload_snapshot={
                    "whitelisted": True,
                    "reason": list_check.reason,
                    "inference_context": _wl_inf,
                    "recommended_action": _wl_rec,
                    "enforcement_action": resolve_enforcement_action("allow", _wl_rec),
                    "challenge_metadata": _wl_meta,
                    "step_trace": step_trace,
                    "counter_version": _audit_counter_version_label(),
                    "rule_pack_file": "",
                    "ml_model": _wl_inf.get("ml_model"),
                    **(
                        {"etl_batch_id": _eb_wl}
                        if (_eb_wl := _metadata_etl_batch_id(body))
                        else {}
                    ),
                    "canary_cohort": build_canary_cohort_audit(
                        body.tenant_id,
                        body.entity_id,
                        salt_version=settings.policy_cohort_salt,
                        experiment_id=settings.policy_experiment_id or None,
                    ),
                },
            )
            session.add(audit)
            await session.commit()
            return EvaluateResponse(
                trace_id=trace_id,
                decision="allow",
                score=0.0,
                tags=["list:whitelist"],
                rule_hits=["whitelist_bypass"],
                reasons=[f"whitelist:{list_check.reason}"],
                ml_score=None,
                inference_context=_wl_inf,
                recommended_action=_wl_rec,
                enforcement_action=resolve_enforcement_action("allow", _wl_rec),
                challenge_policy_id=_wl_meta.get("policy_id"),
                challenge_metadata=_wl_meta,
                policy_set_id=policy_set_id,
            )

        if list_check.action == "deny":
            _bl_inf = build_inference_context(
                ["list:blacklist"],
                ["blacklist_block"],
                None,
                100.0,
                None,
                **_infer_ctx_kwargs(body, {}),
            )
            _bl_base = derive_recommended_action("deny", ["list:blacklist"], _bl_inf)
            _bl_rec, _bl_meta = apply_challenge_policy(
                body.challenge_policy_id,
                _bl_base,
                "deny",
                _bl_inf,
                ["list:blacklist"],
                body.payload,
            )
            audit = AuditRecord(
                trace_id=trace_id,
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision="deny",
                score=100.0,
                tags=["list:blacklist"],
                rule_hits=["blacklist_block"],
                payload_snapshot={
                    "blacklisted": True,
                    "reason": list_check.reason,
                    "inference_context": _bl_inf,
                    "recommended_action": _bl_rec,
                    "enforcement_action": resolve_enforcement_action("deny", _bl_rec),
                    "challenge_metadata": _bl_meta,
                    "step_trace": step_trace,
                    "counter_version": _audit_counter_version_label(),
                    "rule_pack_file": "",
                    "ml_model": _bl_inf.get("ml_model"),
                    **(
                        {"etl_batch_id": _eb_bl}
                        if (_eb_bl := _metadata_etl_batch_id(body))
                        else {}
                    ),
                    "canary_cohort": build_canary_cohort_audit(
                        body.tenant_id,
                        body.entity_id,
                        salt_version=settings.policy_cohort_salt,
                        experiment_id=settings.policy_experiment_id or None,
                    ),
                },
            )
            session.add(audit)
            await session.commit()
            return EvaluateResponse(
                trace_id=trace_id,
                decision="deny",
                score=100.0,
                tags=["list:blacklist"],
                rule_hits=["blacklist_block"],
                reasons=[f"blacklist:{list_check.reason}"],
                ml_score=None,
                inference_context=_bl_inf,
                recommended_action=_bl_rec,
                enforcement_action=resolve_enforcement_action("deny", _bl_rec),
                challenge_policy_id=_bl_meta.get("policy_id"),
                challenge_metadata=_bl_meta,
                policy_set_id=policy_set_id,
            )

    async with acquire_eval_capacity(request.app) as cap:
        _dag = EvalDAGRuntime(load_shed=cap.load_shed)
        if cap.load_shed:
            _metrics_inc_safe("tarka_load_shedding_eval_total", trace_id=trace_id)
        existing_tags = await redis_tags.get_tags(body.tenant_id, body.entity_id)

        if settings.consortium_enabled:
            try:
                signal_hash = hash_entity_id(
                    settings.consortium_secret,
                    body.tenant_id,
                    body.entity_id,
                    hash_scope=settings.consortium_hash_scope,
                )
                consortium_data = await redis_tags.check_consortium_signal(
                    settings.consortium_id, signal_hash
                )
                consortium_delta = consortium_score_delta(
                    consortium_data,
                    min_tenants=settings.consortium_min_tenants,
                    min_reports=settings.consortium_min_reports,
                    trust_floor=settings.consortium_score_trust_floor,
                    max_delta=settings.consortium_score_max_delta,
                )
                if consortium_delta > 0:
                    signal_tags.append("consortium:cross_tenant_hit")
            except Exception:
                consortium_delta = 0.0

        # Graph routing (OSS #42): choose whether to call graph-service and which checkpoint to use.
        graph_checkpoint = _graph_checkpoint_from_body(body)
        graph_routing: dict[str, Any] | None = None
        if not graph_checkpoint:
            # Only apply routing policy when the caller has not pinned a checkpoint explicitly.
            # Base score here is pre-graph: JSON rules + consortium + replay, no graph_delta yet.
            tentative_base = 10.0 + consortium_delta + (20.0 if is_replayed else 0.0)
            graph_routing = decide_graph_routing(
                body.event_type.value, tentative_base, tags=signal_tags
            )
            if graph_routing and graph_routing.get("graph_checkpoint"):
                graph_checkpoint = str(graph_routing["graph_checkpoint"])

        graph_risk = None
        graph_trace = {
            "step": "graph_risk",
            "status": "skipped",
            "reason": "graph_routing_skip",
        }
        if _dag.include_graph():
            if not graph_routing or not graph_routing.get("skip_graph", False):
                graph_risk, graph_trace = await run_evaluation_step(
                    "graph_risk",
                    lambda: _fetch_graph_risk_wrapped(
                        http,
                        body.tenant_id,
                        body.entity_id,
                        degrade_tags,
                        tenant_flags,
                        graph_checkpoint,
                        body.event_type.value,
                    ),
                    timeout_seconds=settings.eval_step_graph_risk_timeout_seconds,
                    max_attempts=settings.eval_step_graph_risk_max_attempts,
                    on_failure="SKIP",
                    fallback=None,
                )
                if graph_risk:
                    graph_delta = graph_score_delta(graph_risk.get("risk_score"))
                    signal_tags.extend(graph_tags_from_risk(graph_risk))
        else:
            graph_trace = {
                "step": "graph_risk",
                "status": "skipped",
                "reason": "load_shedding",
            }
            if "load_shedding:active" not in degrade_tags:
                degrade_tags.append("load_shedding:active")
            _metrics_inc_safe("tarka_load_shedding_active_total", trace_id=trace_id)
        step_trace.append(graph_trace)

        # Feature snapshot (needed before OPA)
        snapshot, snap_trace = await run_evaluation_step(
            "feature_snapshot",
            lambda: _fetch_feature_snapshot_wrapped(
                http, body, existing_tags, degrade_tags, tenant_flags
            ),
            timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
            max_attempts=settings.eval_step_feature_snapshot_max_attempts,
            on_failure="SKIP",
            fallback=_feature_snapshot_fallback(body, existing_tags),
        )
        step_trace.append(snap_trace)
        features: dict[str, Any] = dict(snapshot.get("features") or {})
        redis_tag_list = list(snapshot.get("redis_tags") or existing_tags)

        # Entity linking hints for rules (device ↔ entities, optional vendor bridge)
        if body.device_context and entity_link_store._client:
            linked = await entity_link_store.get_entities_for_device(
                body.tenant_id,
                body.device_context.device_id,
                limit=50,
            )
            others = [e for e in linked if e != body.entity_id]
            if others:
                features["linked_entity_ids"] = others[:20]
                signal_tags.append("sdk:linked_entities")
            if isinstance(body.metadata, dict):
                for vtype, mkey in (
                    ("visitor", "vendor_visitor_id"),
                    ("device", "vendor_device_id"),
                    ("install", "vendor_install_id"),
                ):
                    vid = body.metadata.get(mkey)
                    if isinstance(vid, str) and vid.strip():
                        bridged = await entity_link_store.get_entity_for_vendor(
                            body.tenant_id, vtype, vid.strip()
                        )
                        if bridged and bridged != body.entity_id:
                            features["vendor_bridge_entity_id"] = bridged
                            signal_tags.append("sdk:vendor_entity_bridge")
                        break

        # Merge device signals into features so rules engine can see them
        from decision_api.device_feature_merge import merge_device_context_into_features
        from decision_api.feature_catalog import apply_feature_catalog_v1

        merge_device_context_into_features(features, body.device_context)
        if partner_features:
            features.update(partner_features)
        if body.session_id:
            features.setdefault("session_id", body.session_id)
        # payload amount is often only on body.payload until later merge; expose for catalog
        if "amount" not in features and isinstance(body.payload, dict):
            amt = body.payload.get("amount")
            if amt is not None:
                features.setdefault("amount", amt)
        _fc_fail = frozenset(
            x.strip().lower()
            for x in settings.feature_catalog_fail_closed_event_types.split(",")
            if x.strip()
        )
        apply_feature_catalog_v1(
            features,
            body.event_type.value,
            degrade_tags,
            fail_closed_event_types=_fc_fail,
        )

        if body.agent_context is not None:
            features["agent_context"] = body.agent_context.model_dump(
                mode="json", exclude_none=True
            )

        # Normalise amount to USD if a currency is specified
        payload_currency = body.payload.get("currency")
        if payload_currency and "amount" in body.payload:
            try:
                original_amount = float(body.payload["amount"])
                normalized = await normalize_amount(
                    original_amount, payload_currency, "USD", http
                )
                features["amount"] = normalized
                features["original_amount"] = original_amount
                features["original_currency"] = payload_currency
            except (TypeError, ValueError):
                pass

        # Counter ownership: prefer counter-service as source of truth; keep local aggregates as fallback.
        counter_meta: dict[str, Any] | None = None
        if settings.counter_service_url:
            counter_meta, counter_trace = await run_evaluation_step(
                "counter_snapshot",
                lambda: _fetch_counter_snapshot_wrapped(
                    http, body, features, degrade_tags
                ),
                timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
                max_attempts=settings.eval_step_feature_snapshot_max_attempts,
                on_failure="SKIP",
                fallback=None,
            )
            step_trace.append(counter_trace)
            if isinstance(counter_meta, dict):
                counters = counter_meta.get("counters")
                if isinstance(counters, dict):
                    features.update(counters)
                if counter_meta.get("definition_id"):
                    features["counter_definition_id"] = counter_meta.get(
                        "definition_id"
                    )
                if counter_meta.get("definition_version") is not None:
                    features["counter_definition_version"] = counter_meta.get(
                        "definition_version"
                    )
            elif agg_store._client:
                # Adapter shim while services roll out; keeps evaluate path functional during outages.
                degrade_tags.append("counter:fallback_local_agg")
                agg_features = await agg_store.compute_features(
                    body.tenant_id, body.entity_id, features
                )
                features.update(agg_features)
                if not shadow_request:
                    agg_ts = event_time_unix_for_evaluate(body.metadata, body.payload)
                    await agg_store.record_event(
                        body.tenant_id,
                        body.entity_id,
                        str(trace_id),
                        features,
                        ts=agg_ts,
                    )
        elif agg_store._client:
            agg_features = await agg_store.compute_features(
                body.tenant_id, body.entity_id, features
            )
            features.update(agg_features)
            # Record this event for future aggregate computation (uses normalised amount).
            # Optional metadata.event_time / payload.event_time sets Redis scores to business time (late arrival).
            if not shadow_request:
                agg_ts = event_time_unix_for_evaluate(body.metadata, body.payload)
                await agg_store.record_event(
                    body.tenant_id, body.entity_id, str(trace_id), features, ts=agg_ts
                )

        geo_extra_tags: list[str] = []
        if body.device_context:
            geo_extra_tags = merge_session_geo_from_device_and_features(features)
            for t in geo_extra_tags:
                if t == "sdk:geo_ip_mismatch":
                    features["geo_ip_mismatch"] = True
                elif t == "sdk:geo_tz_mismatch":
                    features["geo_tz_mismatch"] = True
            signal_tags.extend(geo_extra_tags)

        location_meta: dict[str, Any] | None = None
        if settings.location_service_url:
            location_meta, location_trace = await run_evaluation_step(
                "location_eval",
                lambda: _fetch_location_evaluation_wrapped(
                    http, body, features, degrade_tags
                ),
                timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
                max_attempts=settings.eval_step_feature_snapshot_max_attempts,
                on_failure="SKIP",
                fallback=None,
            )
            step_trace.append(location_trace)
            if isinstance(location_meta, dict):
                try:
                    features["geo_consistency_risk"] = float(
                        location_meta.get("geo_consistency_risk")
                    )
                except (TypeError, ValueError):
                    pass
                try:
                    features["copresence_risk"] = float(
                        location_meta.get("copresence_risk")
                    )
                except (TypeError, ValueError):
                    pass
                try:
                    features["impossible_travel_risk"] = float(
                        location_meta.get("impossible_travel_risk")
                    )
                except (TypeError, ValueError):
                    pass
                ltags = location_meta.get("tags")
                if isinstance(ltags, list):
                    signal_tags.extend(str(t) for t in ltags if isinstance(t, str))

        async def _merge_async_osint_redis() -> bool:
            if agg_store._client:
                await merge_cached_async_osint(
                    agg_store._client,
                    body.tenant_id,
                    body.entity_id,
                    features,
                    degrade_tags=degrade_tags,
                    max_age_minutes=settings.async_enrich_max_age_minutes,
                    metrics_inc=_metrics_inc_safe,
                )
            return True

        _osint_pol = dependency_resilience_policy_table().get("async_osint_redis", {})
        _, async_osint_trace = await run_evaluation_step(
            "async_osint_redis",
            _merge_async_osint_redis,
            timeout_seconds=float(_osint_pol.get("timeout_seconds", 0.08)),
            max_attempts=int(_osint_pol.get("max_attempts", 1)),
            on_failure="SKIP",
            fallback=None,
        )
        step_trace.append(async_osint_trace)
        await publish_async_enrichment_request(
            getattr(request.app.state, "message_broker", None),
            body,
            trace_id,
            tenant_flags=tenant_flags,
        )

        # Platform integrity supplements (must run before JSON tag_rules so policy can match integrity:*)
        _plat_kw = _infer_ctx_kwargs(body, features)
        signal_tags.extend(
            supplemental_tags_for_integrity(_plat_kw["platform"], signal_tags)
        )

        # Run rules + OPA + ML in parallel (OPA and ML don't need each other)
        rule_hits, rule_tags, score_delta, json_rule_pack_files = evaluate_json_rules(
            features,
            redis_tag_list,
            body.tenant_id,
            body.entity_id,
            evaluation_mode="production",
            signal_tags=signal_tags,
        )

        opa_task = run_evaluation_step(
            "opa",
            lambda: _evaluate_opa_wrapped(http, snapshot, degrade_tags, tenant_flags),
            timeout_seconds=settings.eval_step_opa_timeout_seconds,
            max_attempts=settings.eval_step_opa_max_attempts,
            on_failure="SKIP",
            fallback=None,
        )
        if _dag.include_ml(snap_trace):
            ml_task = run_evaluation_step(
                "ml_score",
                lambda: _fetch_ml_score_wrapped(
                    http,
                    body.tenant_id,
                    body.entity_id,
                    body.event_type.value,
                    features,
                    degrade_tags,
                    tenant_flags,
                ),
                timeout_seconds=settings.eval_step_ml_timeout_seconds,
                max_attempts=settings.eval_step_ml_max_attempts,
                on_failure="SKIP",
                fallback=(None, {}),
            )
            (opa_result, opa_trace), (ml_pack, ml_trace) = await asyncio.gather(
                opa_task, ml_task, return_exceptions=False
            )
        else:
            opa_result, opa_trace = await opa_task
            ml_pack = (None, {})
            ml_trace = {
                "step": "ml_score",
                "status": "skipped",
                "reason": _dag.ml_skip_reason(snap_trace),
                "attempts": 0,
            }
        step_trace.extend([opa_trace, ml_trace])
        ml_score, ml_detail = ml_pack

        for _dt in degrade_tags:
            if _dt not in signal_tags:
                signal_tags.append(_dt)

        opa_delta = 0.0
        if opa_result and isinstance(opa_result, dict):
            rule_hits.extend(str(x) for x in opa_result.get("rule_hits", []))
            rule_tags.extend(str(t) for t in opa_result.get("tags", []))
            opa_delta = float(opa_result.get("score_delta", 0))
            score_delta += opa_delta

        policy_routing: dict[str, Any] | None = None
        if settings.policy_champion_challenger_enabled:
            _, _, ch_json_delta, _ = evaluate_json_rules(
                features,
                redis_tag_list,
                body.tenant_id,
                body.entity_id,
                evaluation_mode="challenger",
                signal_tags=signal_tags,
            )
            replay_delta_cc = 20.0 if is_replayed else 0.0
            champion_rule_score = (
                10.0 + score_delta + consortium_delta + graph_delta + replay_delta_cc
            )
            challenger_rule_score = (
                10.0
                + ch_json_delta
                + opa_delta
                + consortium_delta
                + graph_delta
                + replay_delta_cc
            )
            policy_routing = build_policy_routing_audit(
                cohort_bucket=cohort_bucket_0_99(
                    body.tenant_id, body.entity_id, settings.policy_cohort_salt
                ),
                cohort_salt=settings.policy_cohort_salt,
                champion_rule_score=champion_rule_score,
                challenger_rule_score=challenger_rule_score,
                champion_decision=decision_from_rule_score(champion_rule_score),
                challenger_decision=decision_from_rule_score(challenger_rule_score),
                ml_score=ml_score if isinstance(ml_score, float) else None,
            )

        signal_tags.extend(
            derive_contextual_tags(
                features=features,
                signal_tags=signal_tags,
                graph_risk=graph_risk if isinstance(graph_risk, dict) else None,
                external_signal_meta=external_signal_meta
                if isinstance(external_signal_meta, dict)
                else None,
            )
        )

        all_new_tags = rule_tags + signal_tags
        if consortium_delta > 0:
            rule_hits.append("consortium_shared_signal")
        if graph_delta > 0:
            rule_hits.append("graph_network_risk")
        replay_delta = 20.0 if is_replayed else 0.0
        base_score = 10.0 + score_delta + consortium_delta + graph_delta + replay_delta
        final_score = _blend_scores(
            base_score, ml_score if isinstance(ml_score, float) else None
        )

        calibration_meta: dict[str, Any] | None = None
        if settings.calibration_service_url:
            if _dag.include_calibration(opa_trace, ml_trace):
                baseline_inf = build_inference_context(
                    list(dict.fromkeys(signal_tags)),
                    rule_hits + replay_rule_hits,
                    ml_score if isinstance(ml_score, float) else None,
                    final_score,
                    features,
                    ml_detail=ml_detail if isinstance(ml_detail, dict) else None,
                    location_meta=location_meta,
                    counter_meta=counter_meta,
                    graph_meta=graph_risk if isinstance(graph_risk, dict) else None,
                    external_signal_meta=external_signal_meta
                    if isinstance(external_signal_meta, dict)
                    else None,
                    policy_experiment_id=settings.policy_experiment_id or None,
                    **_plat_kw,
                )
                baseline_conf = float(baseline_inf.get("integrity_confidence") or 0.0)
                calibration_meta, calibration_trace = await run_evaluation_step(
                    "calibration_adjustment",
                    lambda: _fetch_calibration_adjustment_wrapped(
                        http, body, baseline_conf, features, degrade_tags
                    ),
                    timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
                    max_attempts=settings.eval_step_feature_snapshot_max_attempts,
                    on_failure="SKIP",
                    fallback=None,
                )
                step_trace.append(calibration_trace)
                if isinstance(calibration_meta, dict):
                    cal_conf = calibration_meta.get("calibrated_confidence")
                    if isinstance(cal_conf, (float, int)):
                        features["calibrated_integrity_confidence"] = float(cal_conf)
                    profile_id = calibration_meta.get("profile_id")
                    if isinstance(profile_id, str) and profile_id.strip():
                        features["calibration_profile"] = profile_id.strip()
                    expected_ver = calibration_meta.get("expected_calibration_version")
                    try:
                        if expected_ver is not None:
                            features["expected_calibration_version"] = int(expected_ver)
                    except (TypeError, ValueError):
                        pass
            else:
                reason = (
                    "load_shedding"
                    if _dag.load_shed
                    else "skipped_due_to_dependency_failure"
                )
                step_trace.append(
                    {
                        "step": "calibration_adjustment",
                        "status": "skipped",
                        "reason": reason,
                        "attempts": 0,
                    }
                )

        merged_tags = await redis_tags.merge_tags(
            body.tenant_id, body.entity_id, all_new_tags
        )
        await redis_tags.set_cached_score(body.tenant_id, body.entity_id, final_score)

        combined_rule_hits = rule_hits + replay_rule_hits

        typology_results = evaluate_typologies(combined_rule_hits, features)
        typology_summary = summarize_typologies(typology_results)

        from decision_api.decision_outcome import force_deny_from_degrade_tags

        if force_deny_from_degrade_tags(degrade_tags):
            decision = "deny"
        elif final_score >= settings.deny_threshold:
            decision = "deny"
        elif final_score >= settings.review_threshold:
            decision = "review"
        else:
            decision = "allow"

        reasons: list[str] = []
        if combined_rule_hits:
            reasons.append(f"rules:{','.join(combined_rule_hits)}")
        if signal_tags:
            reasons.append(f"signals:{','.join(signal_tags)}")
        if ml_score is not None and isinstance(ml_score, float):
            reasons.append(f"ml:{ml_score:.2f}")
        merged_signal_tags = list(dict.fromkeys(signal_tags))
        inf_ctx = build_inference_context(
            merged_signal_tags,
            combined_rule_hits,
            ml_score if isinstance(ml_score, float) else None,
            final_score,
            features,
            ml_detail=ml_detail if isinstance(ml_detail, dict) else None,
            calibration_meta=calibration_meta,
            counter_meta=counter_meta,
            location_meta=location_meta,
            graph_meta=graph_risk if isinstance(graph_risk, dict) else None,
            external_signal_meta=external_signal_meta
            if isinstance(external_signal_meta, dict)
            else None,
            policy_experiment_id=settings.policy_experiment_id or None,
            **_plat_kw,
        )
        recommended_action = derive_recommended_action(
            decision, merged_signal_tags, inf_ctx
        )
        recommended_action, ch_meta = apply_challenge_policy(
            body.challenge_policy_id,
            recommended_action,
            decision,
            inf_ctx,
            merged_tags,
            body.payload,
        )
        enforcement_action = resolve_enforcement_action(decision, recommended_action)

        graph_decision_explanation = build_graph_decision_explanation_v1(
            trace_id=str(trace_id),
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            graph_risk=graph_risk if isinstance(graph_risk, dict) else None,
            graph_trace=graph_trace if isinstance(graph_trace, dict) else None,
        )

        # Apply region-aware PII masking before storage
        region = (
            getattr(body, "region", settings.default_region) or settings.default_region
        )
        privacy_profile = get_profile(region)
        raw_snapshot: dict[str, Any] = {
            "payload": body.payload,
            "metadata": body.metadata,
        }
        if body.agent_context is not None:
            raw_snapshot["agent_context"] = body.agent_context.model_dump(
                mode="json", exclude_none=True
            )
        if privacy_profile.mask_pii_in_logs or privacy_profile.pseudonymize_at_rest:
            stored_snapshot = mask_dict(raw_snapshot, privacy_profile)
        else:
            stored_snapshot = raw_snapshot

        fb_reason = _compute_fallback_reason(degrade_tags, step_trace)
        signal_notes = _signal_availability_notes_from_tags(degrade_tags)
        runtime_decision_status = _decision_runtime_status(degrade_tags, signal_notes)
        snap_extra: dict[str, Any] = {
            **stored_snapshot,
            "inference_context": inf_ctx,
            "recommended_action": recommended_action,
            "enforcement_action": enforcement_action,
            "challenge_metadata": ch_meta,
            "step_trace": step_trace,
            "typologies": typology_results,
            "typology_summary": typology_summary,
            "canary_cohort": build_canary_cohort_audit(
                body.tenant_id,
                body.entity_id,
                salt_version=settings.policy_cohort_salt,
                experiment_id=settings.policy_experiment_id or None,
            ),
        }
        if graph_checkpoint:
            snap_extra["graph_checkpoint"] = graph_checkpoint
        if graph_routing is not None:
            snap_extra["graph_routing"] = graph_routing
        if fb_reason:
            snap_extra["fallback_reason"] = fb_reason
        if policy_routing is not None:
            snap_extra["policy_routing"] = policy_routing
        if calibration_meta is not None:
            snap_extra["calibration"] = calibration_meta
        if counter_meta is not None:
            snap_extra["counter"] = counter_meta
        if location_meta is not None:
            snap_extra["location"] = location_meta
        if graph_decision_explanation is not None:
            snap_extra["graph_decision_explanation"] = graph_decision_explanation

        snap_extra["counter_version"] = _audit_counter_version_label()
        snap_extra["rule_pack_file"] = ",".join(json_rule_pack_files)
        snap_extra["ml_model"] = inf_ctx.get("ml_model")
        _eb_snap = _metadata_etl_batch_id(body)
        if _eb_snap:
            snap_extra["etl_batch_id"] = _eb_snap

        snap_extra["decision_status"] = runtime_decision_status
        snap_extra["signal_availability_notes"] = signal_notes
        if policy_set_id:
            snap_extra["policy_set_id"] = policy_set_id
        if shadow_request:
            snap_extra["shadow"] = True
        if partner_evidence:
            snap_extra["partner_evidence"] = partner_evidence
        if partner_graph_hints:
            snap_extra["partner_graph_writeback"] = partner_graph_hints
        _rel_kw = dict(
            tags=merged_tags,
            inference_context=inf_ctx,
            location_meta=location_meta if isinstance(location_meta, dict) else None,
            graph_meta=graph_risk if isinstance(graph_risk, dict) else None,
            partner_graph_hints=partner_graph_hints,
            canary_cohort=snap_extra.get("canary_cohort"),
        )
        relatedness_evidence = build_relatedness_evidence(**_rel_kw)
        if relatedness_evidence is not None:
            snap_extra["relatedness_evidence"] = relatedness_evidence
        location_cohort_evidence = build_location_cohort_evidence(**_rel_kw)
        if location_cohort_evidence is not None:
            snap_extra["location_cohort_evidence"] = location_cohort_evidence

        audit = AuditRecord(
            trace_id=trace_id,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            event_type=body.event_type.value,
            decision=decision,
            score=final_score,
            tags=merged_tags,
            rule_hits=combined_rule_hits,
            payload_snapshot=snap_extra,
        )
        session.add(audit)
        await session.commit()

        decision_log_record = build_decision_log_record(
            trace_id=str(trace_id),
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            event_type=body.event_type.value,
            decision=decision,
            score=final_score,
            tags=merged_tags,
            rule_hits=combined_rule_hits,
            reasons=reasons,
            ml_score=ml_score if isinstance(ml_score, float) else None,
            inference_context=inf_ctx,
            recommended_action=recommended_action,
            enforcement_action=enforcement_action,
            challenge_policy_id=ch_meta.get("policy_id"),
            challenge_metadata=ch_meta,
            fallback_reason=fb_reason,
            payload_snapshot=snap_extra,
            artifact_manifest=_build_artifact_manifest(
                json_rule_pack_files=json_rule_pack_files,
                inf_ctx=inf_ctx,
                graph_checkpoint=graph_checkpoint,
                external_signal_meta=external_signal_meta
                if isinstance(external_signal_meta, dict)
                else None,
                challenge_policy_id=ch_meta.get("policy_id"),
                policy_set_id=policy_set_id,
            ),
        )
        from decision_api.challenge_orchestrator import maybe_dispatch_challenge_webhook
        from decision_api.decision_outcome import (
            DecisionOutcomeContext,
            schedule_decision_outcomes,
        )

        response_tier = _resolve_response_explainability_tier(request)
        response_inf_ctx = _shape_inference_context_for_tier(inf_ctx, response_tier)
        region_profile = get_profile(body.region)
        if region_profile.mask_pii_in_responses:
            response_inf_ctx = mask_dict(response_inf_ctx, region_profile)

        response_graph_explanation = graph_decision_explanation
        if (
            response_graph_explanation is not None
            and region_profile.mask_pii_in_responses
        ):
            response_graph_explanation = mask_dict(
                response_graph_explanation, region_profile
            )

        response = EvaluateResponse(
            trace_id=trace_id,
            decision=decision,
            score=final_score,
            tags=merged_tags,
            rule_hits=combined_rule_hits,
            reasons=reasons,
            ml_score=ml_score if isinstance(ml_score, float) else None,
            inference_context=response_inf_ctx,
            decision_status=runtime_decision_status,
            signal_availability_notes=signal_notes,
            recommended_action=recommended_action,
            enforcement_action=enforcement_action,
            challenge_policy_id=ch_meta.get("policy_id"),
            challenge_metadata=ch_meta,
            fallback_reason=fb_reason,
            graph_decision_explanation=response_graph_explanation,
            policy_set_id=policy_set_id,
        )

        schedule_decision_outcomes(
            bg,
            ctx=DecisionOutcomeContext(
                trace_id=str(trace_id),
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision=decision,
                score=final_score,
                tags=merged_tags,
                rule_hits=combined_rule_hits,
                signal_tags=signal_tags,
                ml_score=ml_score if isinstance(ml_score, float) else None,
                payload=body.payload if isinstance(body.payload, dict) else {},
                metadata=body.metadata if isinstance(body.metadata, dict) else None,
                recommended_action=recommended_action,
                challenge_metadata=ch_meta if isinstance(ch_meta, dict) else None,
                fallback_reason=fb_reason,
                decision_log_record=decision_log_record,
                degrade_tags=list(degrade_tags),
                shadow_request=shadow_request,
            ),
            http=http,
            app_state=request.app.state,
            emit_decision_log=emit_decision_log,
            maybe_dispatch_challenge_webhook=maybe_dispatch_challenge_webhook,
            broadcast_decision=_broadcast_decision,
            publish_decision=_publish_decision,
            metrics_inc=_metrics_inc_safe,
            case_api_url=settings.case_api_url,
            case_create_on_deny_review=settings.case_create_on_deny_review,
            integration_ingress_url=settings.integration_ingress_url,
            ingress_internal_token=settings.ingress_internal_token,
            upstream_headers=_upstream_headers(),
            graph_upsert=_graph_upsert_stepped,
            graph_upsert_args=(
                http,
                body,
                str(trace_id),
                merged_tags,
                geo_extra_tags,
                tenant_flags,
            ),
            shadow_evaluation=_run_shadow_evaluation,
            shadow_args=(
                request.app.state,
                features,
                redis_tag_list,
                decision,
                final_score,
                body.tenant_id,
                str(trace_id),
            ),
        )

        # Test bypass: run full evaluation but override decision to allow
        if list_check and list_check.found and list_check.list_type == "test_bypass":
            _tb_hits = combined_rule_hits + ["test_bypass"]
            _tb_plat = _infer_ctx_kwargs(body, features)
            _tb_extra = supplemental_tags_for_integrity(
                _tb_plat["platform"], signal_tags
            )
            _tb_merged = list(dict.fromkeys(signal_tags + _tb_extra))
            _tb_inf = build_inference_context(
                _tb_merged,
                _tb_hits,
                ml_score if isinstance(ml_score, float) else None,
                final_score,
                features,
                ml_detail=ml_detail if isinstance(ml_detail, dict) else None,
                **_tb_plat,
            )
            _tb_base = derive_recommended_action("allow", _tb_merged, _tb_inf)
            _tb_rec, _tb_meta = apply_challenge_policy(
                body.challenge_policy_id,
                _tb_base,
                "allow",
                _tb_inf,
                signal_tags,
                body.payload,
            )
            response = EvaluateResponse(
                trace_id=trace_id,
                decision="allow",
                score=final_score,
                tags=merged_tags + ["list:test_bypass"],
                rule_hits=_tb_hits,
                reasons=reasons + [f"test_bypass:{list_check.reason}"],
                ml_score=ml_score if isinstance(ml_score, float) else None,
                inference_context=_tb_inf,
                decision_status=runtime_decision_status,
                signal_availability_notes=signal_notes,
                recommended_action=_tb_rec,
                enforcement_action=resolve_enforcement_action("allow", _tb_rec),
                challenge_policy_id=_tb_meta.get("policy_id"),
                challenge_metadata=_tb_meta,
                fallback_reason=fb_reason,
                policy_set_id=policy_set_id,
            )

    return response


# ---------- websocket ----------
