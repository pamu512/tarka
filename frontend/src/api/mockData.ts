type AnyObj = Record<string, unknown>;

const nowIso = () => new Date().toISOString();

let mockCases: AnyObj[] = [
  { id: "c1", title: "Velocity spike - fraud_frank", status: "open", priority: "critical", entity_id: "fraud_frank", tenant_id: "demo", trace_id: "tr-1001", assigned_team: "fraud-ops", labels: ["velocity", "ring"], queue_score: 92, recommended_action: "manual_review", created_at: nowIso(), updated_at: nowIso() },
  { id: "c2", title: "ATO attempt - user_bob", status: "investigating", priority: "high", entity_id: "user_bob", tenant_id: "demo", trace_id: "tr-1002", assigned_team: "ato", labels: ["ato", "vpn"], queue_score: 78, recommended_action: "step_up_auth", created_at: nowIso(), updated_at: nowIso() },
];
let mockDisputes: AnyObj[] = [
  { id: "d1", case_id: "c1", tenant_id: "demo", entity_id: "fraud_frank", trace_id: "tr-1001", dispute_type: "chargeback", status: "open", reason_code: "fraudulent", amount: 1499.99, currency: "USD", merchant_id: "CryptoExchange", card_network: "visa", original_decision: "deny", original_score: 92, original_rule_hits: ["velocity"], original_ml_score: 0.86, outcome: null, resolution_notes: null, filed_at: nowIso(), resolved_at: null, created_at: nowIso(), updated_at: nowIso() },
];
let mockListEntries: AnyObj[] = [
  { list_type: "blocklist", tenant_id: "demo", entity_id: "fraud_frank", reason: "Known fraud ring", created_by: "seed", expires_at: null, metadata: {}, created_at: nowIso() },
  { list_type: "watchlist", tenant_id: "demo", entity_id: "mule_ivan", reason: "Mule behavior", created_by: "seed", expires_at: null, metadata: {}, created_at: nowIso() },
];
let mockInstalledIntegrations: AnyObj[] = [
  { provider_id: "sift", status: "active", category: "device_intelligence" },
  { provider_id: "ip_quality_score", status: "active", category: "ip_intelligence" },
  { provider_id: "jira", status: "active", category: "crm" },
];

function id(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

function parsePath(url: string) {
  return url.split("?")[0];
}

export function getMockResponse(url: string, init?: RequestInit): unknown | null {
  const method = (init?.method ?? "GET").toUpperCase();
  const path = parsePath(url);
  const body = init?.body ? JSON.parse(String(init.body)) : {};

  if (path.includes("/api/decisions/v1/decisions/evaluate")) {
    return {
      trace_id: id("tr"),
      decision: "review",
      score: 74,
      tags: ["synthetic"],
      rule_hits: ["velocity_guard"],
      reasons: ["Demo mode synthetic decision"],
      ml_score: 0.71,
      inference_context: {
        integrity_confidence: 0.78,
        tamper_risk: 0.12,
        network_trust: 0.8,
        replay_risk: 0.05,
        geo_consistency_risk: 0.15,
        top_signals: ["sdk:vpn", "sdk:automation"],
      },
    };
  }
  if (path.includes("/api/decisions/v1/audit/")) {
    return {
      trace_id: path.split("/").pop(),
      entity_id: "demo_entity",
      tenant_id: "demo",
      event_type: "payment",
      decision: "review",
      score: 74,
      tags: ["synthetic"],
      rule_hits: ["velocity_guard"],
      inference_context: {
        integrity_confidence: 0.78,
        tamper_risk: 0.12,
        network_trust: 0.8,
        replay_risk: 0.05,
        geo_consistency_risk: 0.15,
        top_signals: ["sdk:vpn", "sdk:automation"],
      },
      created_at: nowIso(),
    };
  }

  if (path.includes("/api/cases/v1/cases/ops/kpis")) {
    return { tenant_id: "demo", total_cases: mockCases.length, queue_score_avg: 85, critical_open: 1, investigating_rate: 0.4, resolved_rate: 0.2, median_case_age_hours: 6.5 };
  }
  if (path.includes("/api/cases/v1/cases/playbooks")) {
    return { playbooks: { escalate: { label: "Escalate", target_status: "investigating" }, close_fp: { label: "Close False Positive", target_status: "closed" } } };
  }
  if (path.includes("/api/cases/v1/case-views")) {
    if (method === "GET") return { items: [{ name: "High Risk", tenant_id: "demo", filters: { priority: "high" } }] };
    if (method === "POST") return { ok: true, view: { name: body.name ?? "Saved View" } };
    if (method === "DELETE") return { removed: true };
  }
  if (path.includes("/api/cases/v1/cases/bulk-update")) {
    return { updated: (body.case_ids ?? []).length, items: mockCases };
  }
  if (path.includes("/api/cases/v1/cases/") && path.includes("/playbooks/") && method === "POST") {
    return { ok: true, playbook: "demo", case: mockCases[0] };
  }
  if (path.includes("/api/cases/v1/cases") && method === "GET") {
    if (path.match(/\/api\/cases\/v1\/cases\/[^/]+$/)) return mockCases.find((c) => c.id === path.split("/").pop()) ?? mockCases[0];
    return { items: mockCases };
  }
  if (path.includes("/api/cases/v1/cases") && method === "POST") {
    if (path.endsWith("/comments")) return { ok: true };
    if (path.endsWith("/labels")) return { ok: true, labels: body.labels ?? [] };
    const created = { id: id("c"), status: "open", priority: "medium", assigned_team: null, labels: [], created_at: nowIso(), updated_at: nowIso(), ...body };
    mockCases = [created, ...mockCases];
    return created;
  }
  if (path.includes("/api/cases/v1/cases/") && method === "PATCH") {
    return { ...mockCases[0], ...body, updated_at: nowIso() };
  }

  if (path.includes("/api/graph/v1/subgraph")) {
    return { nodes: [{ id: "fraud_frank", labels: ["User"], properties: { risk: "high" } }, { id: "dev_emulator_003", labels: ["Device"], properties: { is_emulator: true } }], edges: [{ from_id: "fraud_frank", to_id: "dev_emulator_003", type: "USED", properties: { shared: true } }] };
  }
  if (path.includes("/api/graph/v1/analytics/entity-risk")) {
    return { entity_id: "fraud_frank", risk_score: 0.94, risk_factors: ["shared_device", "velocity"], connected_flagged_count: 4, community_size: 6 };
  }
  if (path.includes("/api/graph/v1/analytics/communities")) return { communities: [{ community_id: 1, member_count: 6, member_ids: ["fraud_frank"], member_labels: ["User"], shared_attributes: ["device"] }] };
  if (path.includes("/api/graph/v1/analytics/risk-propagation")) return { entities: [{ entity_id: "mule_ivan", entity_labels: ["User"], propagated_risk_score: 0.76, distance: 1, path_description: "fraud_frank -> mule_ivan" }] };
  if (path.includes("/api/graph/v1/analytics/fraud-rings")) return { rings: [{ ring_members: ["fraud_frank", "fraud_gina"], ring_size: 2, relationships: ["COLLABORATES_WITH"], aggregate_tags: ["ring"] }] };

  if (path.includes("/api/analytics/v1/analytics/decisions")) return { rows: [{ decision: "deny", count: 28 }], total: 120 };
  if (path.includes("/api/analytics/v1/analytics/hourly")) return { rows: [{ hour: nowIso(), decision: "deny", event_count: 12, avg_score: 83, deny_count: 6, review_count: 4, allow_count: 2 }] };
  if (path.includes("/api/analytics/v1/analytics/top-entities")) return { decision: "deny", entities: [{ entity_id: "fraud_frank", cnt: 11, avg_score: 91, sample_traces: ["tr-1001"] }] };

  if (path.includes("/api/ml/v1/models")) {
    if (path.match(/\/v1\/models\/[^/]+\/stats/)) return { model: "fraud-gbm", versions: [{ version: 1, total_inferences: 450 }] };
    if (path.match(/\/v1\/models\/[^/]+\/[0-9]+\/lineage/)) return { ok: true, model: "fraud-gbm", version: 1, lineage: { sha256: "9c6d7e8f-demo-lineage", signed_payload: { model: "fraud-gbm", version: 1 } } };
    if (method === "POST") return { ok: true };
    return { models: [{ model_name: "fraud-gbm", version: 1, traffic_weight: 80, active: true, has_onnx: false, total_inferences: 450, avg_latency_ms: 12, metadata: {} }] };
  }

  if (path.includes("/api/decisions/v1/rules/vertical-packs")) {
    if (method === "POST") return { installed: "fintech.json", vertical: "fintech", rules: 8 };
    return { vertical_packs: { fintech: { name: "Fintech", rules: 8, version: 1 } } };
  }
  if (path.includes("/api/decisions/v1/rules/shadow/observations")) return { observations: [{ id: "obs1", production_decision: "allow", shadow_decision: "review" }] };
  if (path.includes("/api/decisions/v1/rules/shadow/stats")) return { total: 120, diverged: 11, divergence_rate: 0.091 };
  if (path.includes("/api/decisions/v1/rules") && method === "GET") return { packs: [{ _file: "default.json", name: "Default", version: 1, rules: [{ id: "velocity_guard", when: [{ field: "amount", op: "gt", value: 500 }], score_delta: 25 }], tag_rules: [] }] };
  if (path.includes("/api/decisions/v1/rules") && ["POST", "PUT", "DELETE"].includes(method)) return { ok: true };

  if (path.includes("/api/decisions/v1/simulation/scenarios")) return { scenarios: { ecommerce: { description: "Synthetic e-commerce scenario" } } };
  if (path.includes("/api/decisions/v1/simulation/run")) return { result: { scenario: "ecommerce", precision: 0.87 }, sample_events: [{ id: "ev1" }], sample_decisions: [{ decision: "deny", score: 82 }] };
  if (path.includes("/api/decisions/v1/simulation/ab-test")) return { winner: "A", confidence: 0.81 };
  if (path.includes("/api/decisions/v1/simulation/benchmark/vertical")) return { scenario: "ecommerce", vertical: "fintech", baseline: { deny_rate: 0.2 }, vertical_pack: { deny_rate: 0.27 }, delta: { deny_rate: 0.07 } };

  if (path.includes("/api/decisions/v1/compliance/regions")) return { regions: { us: { dsar: true }, eu: { dsar: true } } };
  if (path.includes("/api/decisions/v1/compliance/privacy-profile")) return { tenant_id: "demo", region: "us", controls: ["pii_masking"] };
  if (path.includes("/api/decisions/v1/compliance/certifications")) return { items: [{ name: "SOC 2", status: "in_progress" }] };
  if (path.includes("/api/decisions/v1/compliance/dsar/")) return { ok: true, request_id: id("dsar") };
  if (path.includes("/api/decisions/v1/compliance/evidence/controls")) return { tenant_id: "demo", exported_at: nowIso(), controls: [{ id: "cc1", name: "audit", status: "ok" }], summary: {}, evidence: [{ id: "ev1" }] };
  if (path.includes("/api/cases/v1/compliance/evidence")) return { tenant_id: "demo", exported_at: nowIso(), controls: [{ id: "cc1", name: "case_audit", status: "ok" }], summary: {}, evidence: [{ id: "ev2" }] };
  if (path.includes("/api/decisions/v1/compliance/evidence/keys")) return { active_key_id: "k-demo-1", algorithm: "HS256", rotation_supported: true };
  if (path.includes("/api/cases/v1/compliance/evidence/keys")) return { active_key_id: "k-demo-1", algorithm: "HS256", rotation_supported: true };
  if (path.includes("/api/decisions/v1/compliance/evidence/verify")) return { valid: true, active_key_id: "k-demo-1" };
  if (path.includes("/api/cases/v1/compliance/evidence/verify")) return { valid: true, active_key_id: "k-demo-1" };

  if (path.includes("/api/ingress/v1/osint/sources")) return { sources: { email: ["haveibeenpwned"], ip: ["abuseipdb"] }, total_sources: 2 };
  if (path.includes("/api/ingress/v1/osint")) return { composite_risk_score: 73, risk_level: "medium", enrichments: { ip_reputation: "suspicious" }, signals_queried: 6, elapsed_ms: 42 };
  if (path.includes("/api/ingress/v1/integrations/catalog")) return { total_providers: 3, categories: ["ip_intelligence", "device_intelligence", "crm"], providers: [{ id: "ip_quality_score", name: "IPQualityScore", category: "ip_intelligence", type: "api_key", required_config_fields: ["api_key"], doc_url: "https://example.com" }, { id: "sift", name: "Sift", category: "device_intelligence", type: "api_key", required_config_fields: ["api_key"], doc_url: "https://example.com" }, { id: "jira", name: "Jira", category: "crm", type: "credentials", required_config_fields: ["username", "password"], doc_url: "https://example.com" }] };
  if (path.includes("/api/ingress/v1/integrations/installed")) return { tenant_id: "demo", installed: mockInstalledIntegrations, count: mockInstalledIntegrations.length };
  if (path.includes("/api/ingress/v1/integrations/readiness")) return { tenant_id: "demo", readiness_score: 78, covered_categories: 3, total_categories: 9, coverage: { ip_intelligence: { installed: true, count: 1 }, device_intelligence: { installed: true, count: 1 }, crm: { installed: true, count: 1 } } };
  if (path.includes("/api/ingress/v1/integrations/health-matrix")) return { tenant_id: "demo", score: 85, rows: mockInstalledIntegrations.map((i) => ({ provider_id: i.provider_id as string, status: "pass", latency_ms: 120, missing_fields: [] })) };
  if (path.includes("/api/ingress/v1/integrations/install") && method === "POST") return { ok: true, integration: body };
  if (path.includes("/api/ingress/v1/integrations/uninstall") && method === "POST") return { ok: true };
  if (path.includes("/api/ingress/v1/integrations/test-connectivity")) return { provider_id: body.provider_id ?? "demo", status: "pass", latency_ms: 110, missing_fields: [], required_config_fields: [] };
  if (path.includes("/api/ingress/v1/integrations/config/")) return { tenant_id: "demo", provider_id: path.split("/").pop(), required_config_fields: ["api_key"], masked_config: { api_key: "****demo" } };
  if (path.includes("/api/ingress/v1/integrations/configure")) return { ok: true, masked_config: { api_key: "****demo" } };
  if (path.includes("/api/ingress/v1/integrations/request")) return { ok: true, github_issue_url: "https://github.com/pamu512/tarka/issues/999" };
  if (path.includes("/api/ingress/v1/vault/kms")) return { provider: "local", active_key_id: "kms-local-1", rotation_enabled: true, rotation_interval_seconds: 86400, config_valid: true, config_issues: [] };
  if (path.includes("/api/ingress/v1/vault/rotation-jobs")) return { jobs: [{ id: "job-1", status: "completed", old_key_id: "k1", new_key_id: "k2", processed: 150, rotated: 150, failed: 0 }] };
  if (path.includes("/api/ingress/v1/slo")) return { service: "integration-ingress", availability_target: 99.9, latency_target_ms_p95: 300, error_budget_window_days: 30, current: { kms_provider: "local", rotation_jobs: 1, rotation_failures: 0 } };

  if (path.includes("/api/cases/v1/disputes/stats")) return { total: mockDisputes.length, by_status: { open: 1 }, by_type: { chargeback: 1 }, by_outcome: {}, total_amount: 1499.99, win_rate: 0.62 };
  if (path.includes("/api/cases/v1/disputes/entity/")) return { entity_id: "fraud_frank", total_disputes: 1, fraud_confirmed_count: 1, false_positive_count: 0, total_disputed_amount: 1499.99, risk_indicator: "high", disputes: mockDisputes };
  if (path.includes("/api/cases/v1/disputes") && method === "GET") {
    if (path.match(/\/api\/cases\/v1\/disputes\/[^/]+$/)) return mockDisputes[0];
    return { items: mockDisputes };
  }
  if (path.includes("/api/cases/v1/disputes") && method === "POST") {
    const d = { id: id("d"), status: "open", created_at: nowIso(), updated_at: nowIso(), ...body };
    mockDisputes = [d, ...mockDisputes];
    return d;
  }
  if (path.includes("/api/cases/v1/disputes") && method === "PATCH") return { ...mockDisputes[0], ...body, updated_at: nowIso() };

  if (path.includes("/api/decisions/v1/lists/stats/")) return { tenant_id: "demo", stats: { blocklist: 1, allowlist: 1, watchlist: 1 } };
  if (path.includes("/api/decisions/v1/lists/check/")) return { found: true, list_type: "watchlist", action: "review", reason: "Synthetic watchlist hit" };
  if (path.includes("/api/decisions/v1/lists/") && method === "GET") {
    const parts = path.split("/");
    const listType = parts[parts.length - 1];
    const entries = mockListEntries.filter((e) => e.list_type === listType);
    return { list_type: listType, tenant_id: "demo", count: entries.length, entries };
  }
  if (path.includes("/api/decisions/v1/lists/") && method === "POST") {
    if (path.endsWith("/bulk")) {
      const added = (body.entries ?? []).map((e: AnyObj) => ({ list_type: path.split("/").slice(-2, -1)[0], tenant_id: "demo", entity_id: e.entity_id, reason: e.reason ?? "", created_by: "ui", expires_at: null, metadata: {}, created_at: nowIso() }));
      mockListEntries = [...added, ...mockListEntries];
      return { added: added.length, entries: added };
    }
    const created = { list_type: path.split("/").pop(), tenant_id: "demo", created_at: nowIso(), ...body };
    mockListEntries = [created, ...mockListEntries];
    return created;
  }
  if (path.includes("/api/decisions/v1/lists/") && method === "DELETE") return { removed: true };

  if (path.includes("/api/investigation/v1/chat")) return { reply: "Synthetic analyst response: likely fraud ring using shared emulator and VPN indicators.", tool_calls: [] };

  return null;
}
