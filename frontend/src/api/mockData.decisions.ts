import { deterministicAuditRecentItem } from "../domain/auditExplorerDeterministic";
import { type AnyObj, mockRandomAlpha } from "./mockData.shared";

export type DecisionsMockRequest = {
  url: string;
  path: string;
  method: string;
  body: AnyObj;
};

const nowIso = () => new Date().toISOString();

function id(prefix: string) {
  return `${prefix}-${mockRandomAlpha(6)}`;
}

/**
 * Decision-api / ops mock slice (`/api/decisions/v1/*` evaluate, audit, posture, calibration).
 * Returns null when the path is not owned by this slice.
 */
export function getDecisionsMockResponse(req: DecisionsMockRequest): unknown | null {
  const { url, path, method, body } = req;
  if (!path.includes("/api/decisions/v1/")) return null;

  if (path.includes("/api/decisions/v1/replay") && method === "POST") {
    const tid = String(body.tenant_id ?? "demo");
    const traceRaw = body.trace_ids;
    const traceIds = Array.isArray(traceRaw)
      ? traceRaw.map((x) => String(x)).filter(Boolean)
      : [];
    const lim = typeof body.limit === "number" ? Math.min(5000, Math.max(1, body.limit)) : 25;
    const n = traceIds.length > 0 ? traceIds.length : Math.min(lim, 4);
    const rows: Array<{
      trace_id: string;
      entity_id: string;
      event_type: string;
      original_decision: string;
      original_score: number;
      original_rule_hits: string[];
      new_decision: string;
      new_score: number;
      new_rule_hits: string[];
      new_tags: string[];
      score_diff: number;
      decision_changed: boolean;
    }> = [];
    for (let i = 0; i < n; i++) {
      const traceId =
        traceIds[i] ?? `00000000-0000-4000-8000-${String(1000 + i).padStart(12, "0")}`;
      const origScore = 40 + i * 5;
      const changed = i % 2 === 0;
      rows.push({
        trace_id: traceId,
        entity_id: `ent-sb-${i}`,
        event_type: "payment",
        original_decision: "review",
        original_score: origScore,
        original_rule_hits: ["velocity_guard"],
        new_decision: changed ? "deny" : "review",
        new_score: Math.min(100, origScore + 25),
        new_rule_hits: changed ? ["draft_sandbox"] : [],
        new_tags: changed ? ["sandbox"] : [],
        score_diff: 25,
        decision_changed: changed,
      });
    }
    return {
      tenant_id: tid,
      events_evaluated: rows.length,
      decisions_changed: rows.filter((r) => r.decision_changed).length,
      results: rows,
      missing_trace_ids: [] as string[],
    };
  }

  if (path.includes("/api/decisions/v1/decisions/evaluate")) {
    return {
      trace_id: id("tr"),
      decision: "review",
      score: 74,
      tags: ["synthetic"],
      rule_hits: ["velocity_guard"],
      reasons: ["Demo mode synthetic decision"],
      ml_score: 0.71,
      recommended_action: "manual_review",
      inference_context: {
        schema_version: "3",
        calibration_profile: "default",
        expected_calibration_version: 1,
        integrity_confidence: 0.78,
        tamper_risk: 0.12,
        network_trust: 0.8,
        replay_risk: 0.05,
        geo_consistency_risk: 0.15,
        top_signals: ["sdk:vpn", "sdk:automation"],
        confidence_tier: "medium",
        driver_reasons: ["hostile_or_anonymous_network_path", "rule:velocity_guard"],
        colocation_risk: 0,
        copresence_risk: 0,
        impossible_travel_risk: 0.1,
        velocity_events_5m: 2,
        velocity_events_1h: 12,
        velocity_events_24h: 48,
        velocity_events_by_hour_utc: [
          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 4, 8, 18, 12, 4, 0, 0, 0, 0, 0, 0, 0,
        ],
        calibration_profile_version: 1,
        location_confidence: 0.74,
        confidence_sources: { calibration: "service", counter: "service", location: "service" },
        graph_risk_score: 0.22,
        graph_risk_reasons: [],
        external_signal_score: 0,
        external_signal_providers: [],
        policy_experiment_id: null,
        ml_model: "heuristic-v1",
        ml_summary:
          "ML risk score 71.0/100 (heuristic-v1). Top signals: ELEVATED_RISK: Overall risk score 71/100 — elevated risk, manual review recommended",
        ml_top_factors: [
          {
            code: "ELEVATED_RISK",
            description: "Overall risk score 71/100 — elevated risk, manual review recommended",
            impact: "high",
          },
          {
            code: "VPN_DETECTED",
            description: "VPN or proxy connection detected",
            impact: "high",
          },
        ],
      },
    };
  }
  if (path.includes("/api/decisions/v1/micro-dev/onboarding/status")) {
    return {
      lifecycle_state: "ready",
      engine: "sqlite",
      analytics_store: "clickhouse",
      checks: [],
    };
  }
  if (path.includes("/api/decisions/v1/micro-dev/onboarding/verify/sqlite")) {
    return { status: "ok", check: "sqlite_permissions", detail: { scope: "mock" } };
  }
  if (path.includes("/api/decisions/v1/micro-dev/onboarding/verify/duckdb")) {
    return { status: "ok", check: "duckdb_bindings", detail: { scope: "mock" } };
  }
  if (path.includes("/api/decisions/v1/challenge-policies")) {
    return {
      policies: [
        {
          policy_id: "default_v1",
          version: 1,
          description: "Default escalation ladder",
          escalation_ladder: ["step_up_mfa", "step_up_attestation", "manual_review", "block"],
        },
        {
          policy_id: "strict_review_v1",
          version: 1,
          description: "Stricter review thresholds",
          escalation_ladder: ["manual_review", "block"],
        },
      ],
    };
  }

  if (path.includes("/api/decisions/v1/slo")) {
    return {
      service: "decision-api",
      availability_target_pct: 99.9,
      latency_target_ms_p95: 50,
      error_budget_window_days: 30,
      current: {
        redis_connected: true,
        nats_connected: true,
        total_requests: 42,
      },
      degraded_decisions: {
        total: 3,
        by_reason: { load_shed: 1, async_enrich_stale: 1, missing_feature: 1 },
      },
    };
  }
  if (path.includes("/api/decisions/v1/ops/evaluation-posture")) {
    return {
      service: "decision-api",
      deployment_tier: "pro",
      tenant_reliability_profile: "balanced",
      evaluation_mode: "detection",
      compliance_posture: "ready",
      compliance_degraded: false,
      compliance_degraded_reasons: [],
      typology_count: 2,
      predicate_registry_version: 1,
      predicate_registry_pin_match: true,
      dependencies: [
        { id: "redis", ok: true, detail: "connected" },
        { id: "graph_service_configured", ok: true, detail: "set" },
        { id: "feature_service_configured", ok: false, detail: "empty" },
        { id: "ml_scoring_configured", ok: false, detail: "empty" },
        { id: "nats_configured", ok: true, detail: "set" },
        { id: "opa_configured", ok: false, detail: "empty" },
      ],
      last_rules_reload_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      runbook_url: "https://github.com/pamu512/tarka/blob/master/docs/docs/guides/deployment-profiles-community-vs-pro.md",
      request_id: null,
    };
  }
  if (path.includes("/api/decisions/v1/ops/governance")) {
    return {
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 2, shadow_pack_count: 1, packs: [] },
      counter_catalog: {
        endpoint: "GET /v1/internal/counters/catalog",
        note: "Merged manifest + titles",
      },
      experiment_registry_lines: 0,
      drift_smoke: { script: "scripts/benchmarks/drift_score_smoke.py", note: "Baseline vs shifted separation guard." },
    };
  }
  if (path.includes("/api/decisions/v1/internal/counters/catalog")) {
    return {
      catalog_version: "1",
      manifest_version: "1.0.0",
      redis_key_version: null,
      counters: [
        { name: "event_count_1h", title: "Events (1 hour)", category: "volume", kind: "event_count", window_seconds: 3600 },
      ],
    };
  }

  if (path === "/api/decisions/v1/audit/recent") {
    const t = Date.now();
    const cycle = ["ALLOW", "DENY", "REVIEW", "SHADOW_REVIEW"] as const;
    const demoDeterministic: Record<string, unknown> = {
      trace_id: "deterministic-ai-bypass-demo",
      short_id: "DETERMIN",
      amount: 100,
      currency: "USD",
      rule_result: "DENY",
      ai_confidence: null,
      created_at: new Date(t - 60_000).toISOString(),
    };
    const items = Array.from({ length: 20 }, (_, i) => {
      const trace_id = `a${(t + i).toString(16).padStart(7, "0")}-b00${i}-4000-8000-${((t + i * 7919) >>> 0).toString(16).padStart(12, "0")}`;
      const hex = trace_id.replace(/-/g, "");
      const short_id = hex.slice(0, 8).toUpperCase();
      const rr = cycle[i % cycle.length]!;
      return {
        trace_id,
        short_id,
        amount: Math.round((12.5 + i * 3.17 + (t % 97)) * 100) / 100,
        currency: "USD",
        rule_result: rr,
        ai_confidence: Math.min(0.99, 0.35 + ((i * 17 + t) % 60) / 100),
        created_at: new Date(t - i * 1500).toISOString(),
      };
    });
    return { tenant_id: "demo", items: [demoDeterministic, ...items] };
  }
  if (path.includes("/api/decisions/v1/audit/explorer") && method === "GET") {
    let urlObj: URL;
    try {
      urlObj = new URL(url, "http://mock.local");
    } catch {
      urlObj = new URL("http://mock.local/");
    }
    const tenant_id = urlObj.searchParams.get("tenant_id") ?? "demo";
    const limit = Math.min(500, Math.max(1, Number(urlObj.searchParams.get("limit")) || 200));
    const qRaw = (urlObj.searchParams.get("q") ?? "").trim().toLowerCase();
    const cursorRaw = urlObj.searchParams.get("cursor") ?? "";

    const matches = (
      r: ReturnType<typeof deterministicAuditRecentItem>,
      q: string,
    ): boolean => {
      if (!q) return true;
      return r.trace_id.toLowerCase().includes(q) || r.short_id.toLowerCase().includes(q);
    };

    if (!qRaw) {
      let start = 0;
      try {
        const c = cursorRaw ? (JSON.parse(atob(cursorRaw)) as { o?: unknown }) : {};
        start = typeof c.o === "number" && Number.isFinite(c.o) ? Math.max(0, Math.floor(c.o)) : 0;
      } catch {
        start = 0;
      }
      const items = [];
      for (let i = 0; i < limit; i++) {
        items.push(deterministicAuditRecentItem(start + i));
      }
      return {
        tenant_id,
        items,
        next_cursor: btoa(JSON.stringify({ o: start + limit })),
        approx_total_rows: null,
      };
    }

    let scan = 0;
    let storedQ = "";
    try {
      const c = cursorRaw ? (JSON.parse(atob(cursorRaw)) as { scan?: unknown; q?: unknown }) : {};
      scan = typeof c.scan === "number" && Number.isFinite(c.scan) ? Math.max(0, Math.floor(c.scan)) : 0;
      storedQ = typeof c.q === "string" ? c.q : "";
    } catch {
      scan = 0;
      storedQ = "";
    }
    if (storedQ !== qRaw) {
      scan = 0;
    }

    const items: ReturnType<typeof deterministicAuditRecentItem>[] = [];
    let s = scan;
    const MAX_SCAN_STEP = 350_000;
    let stepped = 0;
    while (items.length < limit && stepped < MAX_SCAN_STEP) {
      const r = deterministicAuditRecentItem(s);
      if (matches(r, qRaw)) items.push(r);
      s++;
      stepped++;
    }
    const exhausted = stepped >= MAX_SCAN_STEP && items.length < limit;
    const next_cursor = exhausted ? null : btoa(JSON.stringify({ scan: s, q: qRaw }));

    return {
      tenant_id,
      items,
      next_cursor,
      approx_total_rows: null,
    };
  }
  if (path.includes("/api/decisions/v1/audit/")) {
    const traceId = (path.split("/").pop() ?? "demo").split("?")[0] ?? "demo";
    let detailLevel = "minimal";
    try {
      detailLevel = new URL(url, "http://mock.local").searchParams.get("detail_level") ?? "minimal";
    } catch {
      detailLevel = "minimal";
    }
    const analystPayload =
      detailLevel === "analyst" || detailLevel === "full"
        ? {
            schema_version: "1",
            transaction_id: traceId,
            amount_cents: 12999,
            currency: "USD",
            channel: "card_not_present",
            merchant_id: "merch_demo",
            instrument_fingerprint: "fp_demo_redacted",
            ip_asn: "AS13335",
            geo_country: "US",
            shipping_country: "US",
            geo_collision: {
              ip: { lat: 37.7749, lng: -122.4194, label: "Session IP (San Francisco, CA)" },
              shipping: { lat: 34.0522, lng: -118.2437, label: "Ship-to (Los Angeles, CA)" },
            },
            mcc: "5999",
            velocity_window_minutes: 60,
            prior_declines_24h: 0,
            metadata: { source: "mock_audit_evaluate_payload" },
          }
        : undefined;
    const malformedDemo = traceId === "tr-malformed-trace";
    if (traceId === "deterministic-ai-bypass-demo") {
      return {
        trace_id: traceId,
        entity_id: "demo_entity",
        tenant_id: "demo",
        event_type: "payment",
        decision: "deny",
        score: 99,
        tags: ["synthetic", "rules_only_path"],
        rule_hits: ["hard_velocity_cap"],
        recommended_action: null,
        fallback_reason: "rules_only",
        step_trace: [
          { step: "velocity_rules", status: "ok", duration_ms: 2 },
          { step: "aggregate_decision", status: "ok", duration_ms: 0 },
        ],
        inference_context: {
          schema_version: "3",
          calibration_profile: "default",
          expected_calibration_version: 1,
          integrity_confidence: 0,
          tamper_risk: 0,
          network_trust: 0,
          replay_risk: 0,
          geo_consistency_risk: 0,
          top_signals: [],
          confidence_tier: "low",
          driver_reasons: ["rule:hard_velocity_cap"],
          driver_explain: [],
          colocation_risk: 0,
          copresence_risk: 0,
          impossible_travel_risk: 0,
          velocity_events_5m: 0,
          velocity_events_1h: 0,
          velocity_events_24h: 0,
          calibration_profile_version: 1,
          location_confidence: 0,
          confidence_sources: { calibration: "skipped", counter: "skipped", location: "skipped" },
          graph_risk_score: 0,
          graph_risk_reasons: [],
          external_signal_score: 0,
          external_signal_providers: [],
          policy_experiment_id: null,
          ml_model: null,
          ml_summary: null,
          ml_top_factors: [],
        },
        explanation_drivers: [],
        evaluate_payload: analystPayload ?? {
          schema_version: "1",
          transaction_id: traceId,
          amount_cents: 100,
          currency: "USD",
          channel: "ach",
          merchant_id: "merch_x",
          instrument_fingerprint: "fp_x",
          ip_asn: "AS64500",
          geo_country: "US",
          mcc: "4829",
          velocity_window_minutes: 30,
          prior_declines_24h: 9,
          metadata: {},
        },
        created_at: nowIso(),
      };
    }
    return {
      trace_id: traceId,
      entity_id: "demo_entity",
      tenant_id: "demo",
      event_type: "payment",
      decision: "review",
      score: 74,
      tags: ["synthetic"],
      rule_hits: ["velocity_guard"],
      recommended_action: "manual_review",
      fallback_reason: malformedDemo ? "partial_snapshot" : null,
      step_trace: malformedDemo
        ? ("not-a-json-array" as unknown)
        : [
            { step: "ingest_normalize", status: "ok", duration_ms: 1 },
            { step: "list_checks", status: "ok", duration_ms: 0 },
            { step: "sanctions_vendor", status: "skipped", reason: "routing: alternate path — primary vendor timeout" },
            { step: "velocity_rules", status: "ok", duration_ms: 4 },
            { step: "ml_host", status: "failed", reason: "http_error: upstream 503", duration_ms: 120 },
            { step: "aggregate_decision", status: "skipped", reason: "downstream: ml_host failed" },
          ],
      explanation_drivers: [
        {
          reason: "rule:velocity_guard",
          category: "rules",
          label: "Velocity guard",
          rank: 1,
          source: "driver_reasons",
        },
        {
          reason: "hostile_or_anonymous_network_path",
          category: "network",
          label: "VPN / hostile path",
          rank: 2,
          source: "driver_explain",
        },
      ],
      evaluate_payload: analystPayload,
      inference_context: {
        schema_version: "3",
        calibration_profile: "default",
        expected_calibration_version: 1,
        integrity_confidence: 0.78,
        tamper_risk: 0.12,
        network_trust: 0.8,
        replay_risk: 0.05,
        geo_consistency_risk: 0.15,
        top_signals: ["sdk:vpn", "sdk:automation"],
        confidence_tier: "medium",
        driver_reasons: ["hostile_or_anonymous_network_path", "rule:velocity_guard"],
        driver_explain: [
          {
            reason: "hostile_or_anonymous_network_path",
            category: "network",
            label: "VPN, proxy, or hostile network path",
          },
        ],
        colocation_risk: 0,
        copresence_risk: 0,
        impossible_travel_risk: 0.1,
        velocity_events_5m: 2,
        velocity_events_1h: 12,
        velocity_events_24h: 48,
        velocity_events_by_hour_utc: [
          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 4, 8, 18, 12, 4, 0, 0, 0, 0, 0, 0, 0,
        ],
        calibration_profile_version: 1,
        location_confidence: 0.74,
        confidence_sources: { calibration: "service", counter: "service", location: "service" },
        graph_risk_score: 0.22,
        graph_risk_reasons: [],
        external_signal_score: 0,
        external_signal_providers: [],
        policy_experiment_id: null,
        ml_model: "heuristic-v1",
        ml_summary:
          "ML risk score 71.0/100 (heuristic-v1). Top signals: ELEVATED_RISK: Overall risk score 71/100 — elevated risk, manual review recommended",
        ml_top_factors: [
          {
            code: "ELEVATED_RISK",
            description: "Overall risk score 71/100 — elevated risk, manual review recommended",
            impact: "high",
          },
          {
            code: "VPN_DETECTED",
            description: "VPN or proxy connection detected",
            impact: "high",
          },
        ],
      },
      created_at: nowIso(),
    };
  }


  if (path.includes("/api/decisions/v1/ops/calibration-status")) {
    return {
      tenant_id: "demo",
      profile: "default",
      inference_schema_version: "3",
      challenge_policy_default: "balanced",
      calibration: {
        tenant_id: "demo",
        profile: "default",
        drift_score: 0.08,
        hint: "ok",
        latest_ts: nowIso(),
        reference_set_at: nowIso(),
      },
    };
  }
  if (path.includes("/api/decisions/v1/calibration/drift")) {
    return { tenant_id: "demo", profile: "default", drift_score: 0.08, hint: "ok" };
  }
  if (path.includes("/api/decisions/v1/calibration/summary")) {
    return {
      tenant_id: "demo",
      profile: "default",
      snapshots: [
        {
          ts: nowIso(),
          sample_count: 1200,
          mean_integrity: 0.72,
          mean_final_score: 64.2,
          notes: "mock snapshot",
        },
      ],
    };
  }

  if (path.includes("/api/decisions/v1/policy/posture")) {
    return {
      schema: "tarka.policy_set/v1",
      policy_set_id: "a".repeat(64),
      components: {
        json_packs: [
          {
            file: "default.json",
            name: "Default",
            mode: "active",
            rule_count: 1,
            sha256: "b".repeat(64),
          },
        ],
        typology: {
          file: "typology_definitions_v1.json",
          version: 1,
          typology_count: 2,
          sha256: "c".repeat(64),
        },
        challenge_policies: [{ policy_id: "default_v1", version: 1, sha256: "d".repeat(64) }],
      },
      counts: { json_packs: 1, typologies: 2, challenge_policies: 1 },
    };
  }

  return null;
}
