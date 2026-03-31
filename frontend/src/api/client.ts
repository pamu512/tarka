// ── Types ────────────────────────────────────────────────────────────

export interface DecisionRequest {
  event_type: string;
  entity_id: string;
  tenant_id: string;
  session_id?: string;
  payload?: Record<string, unknown>;
  device_context?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface DecisionResponse {
  trace_id: string;
  decision: "allow" | "review" | "deny";
  score: number;
  tags: string[];
  rule_hits: string[];
  reasons: string[];
  ml_score: number | null;
}

export interface AuditEntry {
  trace_id: string;
  entity_id: string;
  tenant_id: string;
  event_type: string;
  decision: string;
  score: number;
  tags: string[];
  rule_hits: string[];
  created_at: string;
}

export interface Case {
  id: string;
  title: string;
  status: "open" | "investigating" | "resolved" | "closed";
  priority: "critical" | "high" | "medium" | "low";
  entity_id: string;
  tenant_id: string;
  trace_id: string;
  assigned_team: string | null;
  labels: string[];
  created_at: string;
  updated_at: string;
}

export interface CaseComment {
  author: string;
  body: string;
  created_at: string;
}

export interface CaseCreateRequest {
  title: string;
  entity_id: string;
  tenant_id: string;
  trace_id: string;
  priority?: string;
}

export interface GraphNode {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  from_id: string;
  to_id: string;
  type: string;
  properties?: Record<string, unknown>;
}

export interface SubgraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface CommunityResult {
  community_id: number;
  member_count: number;
  member_ids: string[];
  member_labels: string[];
  shared_attributes: string[];
}

export interface FraudRingResult {
  ring_members: string[];
  ring_size: number;
  relationships: string[];
  aggregate_tags: string[];
}

export interface EntityRiskResult {
  entity_id: string;
  risk_score: number;
  risk_factors: string[];
  connected_flagged_count: number;
  community_size: number;
}

export interface RiskPropagationResult {
  entity_id: string;
  entity_labels: string[];
  propagated_risk_score: number;
  distance: number;
  path_description: string;
}

export interface AnalyticsSummary {
  total_decisions: number;
  deny_rate: number;
  review_rate: number;
  avg_score: number;
}

export interface HourlyStat {
  hour: string;
  decision: string;
  event_count: number;
  avg_score: number;
  deny_count: number;
  review_count: number;
  allow_count: number;
}

export interface TopEntity {
  entity_id: string;
  cnt: number;
  avg_score: number;
  sample_traces: string[];
}

export interface ModelInfo {
  name: string;
  versions: Record<string, unknown>[];
}

export interface RulePack {
  _file: string;
  name: string;
  version: number;
  rules: RuleDetail[];
  tag_rules: TagRuleDetail[];
}

export interface RuleDetail {
  id: string;
  when: { field: string; op: string; value: unknown }[];
  score_delta: number;
  description?: string;
  tags?: string[];
  enabled?: boolean;
}

export interface TagRuleDetail {
  id: string;
  when: { field: string; op: string; value: unknown }[];
  tags: string[];
}

export interface RuleSimulationResult {
  decision: string;
  score: number;
  rule_hits: string[];
  signal_tags: string[];
}

// ── Fetcher ──────────────────────────────────────────────────────────

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  return res.json();
}

// ── Decisions (decision-api :8000) ──────────────────────────────────

export const decisions = {
  evaluate(payload: DecisionRequest) {
    return request<DecisionResponse>("/api/decisions/v1/decisions/evaluate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getAudit(traceId: string) {
    return request<AuditEntry>(`/api/decisions/v1/audit/${traceId}`);
  },

  replay(body: { tenant_id: string; rules_override: unknown[]; limit?: number }) {
    return request<{
      tenant_id: string;
      events_evaluated: number;
      decisions_changed: number;
      results: unknown[];
    }>("/api/decisions/v1/replay", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};

// ── Cases (case-api :8002) ──────────────────────────────────────────

export const cases = {
  list(params: { tenant_id: string; status?: string; limit?: number }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.status) q.set("status", params.status);
    if (params.limit) q.set("limit", String(params.limit));
    return request<{ items: Case[] }>(`/api/cases/v1/cases?${q}`);
  },

  get(caseId: string) {
    return request<Case>(`/api/cases/v1/cases/${caseId}`);
  },

  create(data: CaseCreateRequest) {
    return request<Case>("/api/cases/v1/cases", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  update(caseId: string, data: Partial<Pick<Case, "status" | "priority" | "assigned_team" | "title">>) {
    return request<Case>(`/api/cases/v1/cases/${caseId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  addComment(caseId: string, author: string, body: string) {
    return request<{ ok: boolean }>(`/api/cases/v1/cases/${caseId}/comments`, {
      method: "POST",
      body: JSON.stringify({ author, body }),
    });
  },

  addLabels(caseId: string, labels: string[]) {
    return request<{ ok: boolean; labels: string[] }>(
      `/api/cases/v1/cases/${caseId}/labels`,
      { method: "POST", body: JSON.stringify({ labels }) },
    );
  },

  getSla(caseId: string) {
    return request<{
      case_id: string;
      priority: string;
      sla_deadline: string;
      breached: boolean;
      status: string;
    }>(`/api/cases/v1/cases/${caseId}/sla`);
  },

  getAudit(caseId: string) {
    return request<{ history: unknown[] }>(`/api/cases/v1/cases/${caseId}/audit`);
  },

  generateSar(caseId: string, format: string = "fincen_xml") {
    return request<unknown>(`/api/cases/v1/cases/${caseId}/sar/generate`, {
      method: "POST",
      body: JSON.stringify({ format }),
    });
  },
};

// ── Graph (graph-service :8001) ─────────────────────────────────────

export const graph = {
  subgraph(entityId: string, tenantId: string, depth?: number) {
    const q = new URLSearchParams({ entity_id: entityId, tenant_id: tenantId });
    if (depth) q.set("depth", String(depth));
    return request<SubgraphResponse>(`/api/graph/v1/subgraph?${q}`);
  },

  entityTags(entityId: string, tenantId: string) {
    return request<{ tags: string[] }>(
      `/api/graph/v1/entities/${entityId}/tags?tenant_id=${tenantId}`,
    );
  },

  communities(tenantId: string, minSize?: number) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    if (minSize) q.set("min_size", String(minSize));
    return request<{ communities: CommunityResult[] }>(
      `/api/graph/v1/analytics/communities?${q}`,
    );
  },

  riskPropagation(entityId: string, tenantId: string, depth?: number) {
    const q = new URLSearchParams({ entity_id: entityId, tenant_id: tenantId });
    if (depth) q.set("depth", String(depth));
    return request<{ entities: RiskPropagationResult[] }>(
      `/api/graph/v1/analytics/risk-propagation?${q}`,
    );
  },

  fraudRings(tenantId: string, minSize?: number) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    if (minSize) q.set("min_size", String(minSize));
    return request<{ rings: FraudRingResult[] }>(
      `/api/graph/v1/analytics/fraud-rings?${q}`,
    );
  },

  entityRisk(entityId: string, tenantId: string) {
    return request<EntityRiskResult>(
      `/api/graph/v1/analytics/entity-risk?entity_id=${entityId}&tenant_id=${tenantId}`,
    );
  },
};

// ── Analytics (analytics-sink :8008) ────────────────────────────────

export const analytics = {
  decisions(params?: { tenant_id?: string; limit?: number }) {
    const q = new URLSearchParams();
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    if (params?.limit) q.set("limit", String(params.limit));
    return request<{ rows: unknown[]; total: number }>(`/api/analytics/v1/analytics/decisions?${q}`);
  },

  hourly(params?: { tenant_id?: string; days?: number }) {
    const q = new URLSearchParams();
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    if (params?.days) q.set("days", String(params.days));
    return request<{ rows: HourlyStat[] }>(`/api/analytics/v1/analytics/hourly?${q}`);
  },

  topEntities(params?: { tenant_id?: string; limit?: number }) {
    const q = new URLSearchParams();
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    if (params?.limit) q.set("limit", String(params.limit));
    return request<{ decision: string; entities: TopEntity[] }>(
      `/api/analytics/v1/analytics/top-entities?${q}`,
    );
  },
};

// ── ML (ml-scoring :8005) ───────────────────────────────────────────

export const ml = {
  models() {
    return request<{ models: ModelInfo[] }>("/api/ml/v1/models");
  },

  modelStats(modelName: string) {
    return request<{ model: string; versions: unknown }>(
      `/api/ml/v1/models/${modelName}/stats`,
    );
  },
};

// ── Rules (decision-api :8000, /v1/rules router) ────────────────────

export const rules = {
  list() {
    return request<{ packs: RulePack[] }>("/api/decisions/v1/rules");
  },

  create(data: { name: string; rules?: unknown[]; tag_rules?: unknown[] }) {
    return request<unknown>("/api/decisions/v1/rules", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  update(filename: string, data: { name: string; rules: unknown[]; tag_rules?: unknown[] }) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  deletePack(filename: string) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}`, {
      method: "DELETE",
    });
  },

  addRule(filename: string, rule: unknown) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}/rules`, {
      method: "POST",
      body: JSON.stringify(rule),
    });
  },

  deleteRule(filename: string, ruleId: string) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}/rules/${ruleId}`, {
      method: "DELETE",
    });
  },

  reload() {
    return request<{ ok: boolean }>("/api/decisions/v1/admin/rules/reload", {
      method: "POST",
    });
  },

  simulate(payload: DecisionRequest) {
    return decisions.evaluate(payload);
  },
};

// ── Shadow Mode (decision-api :8000) ────────────────────────────────

export const shadow = {
  observations(limit?: number) {
    return request<{ observations: unknown[] }>(
      `/api/decisions/v1/rules/shadow/observations?limit=${limit ?? 100}`,
    );
  },

  stats() {
    return request<{
      total: number;
      diverged?: number;
      divergence_rate?: number;
      production_distribution?: Record<string, number>;
      shadow_distribution?: Record<string, number>;
      confusion_matrix?: { tp: number; fp: number; fn: number; tn: number };
      avg_score_delta?: number;
      score_delta_p95?: number;
    }>("/api/decisions/v1/rules/shadow/stats");
  },

  setPackMode(filename: string, mode: string) {
    return request<{ file: string; mode: string }>(
      `/api/decisions/v1/rules/${filename}/mode`,
      {
        method: "PUT",
        body: JSON.stringify({ mode }),
      },
    );
  },
};

// ── Recommendations (decision-api :8000) ────────────────────────────

export const recommendations = {
  generate(tenantId: string, lookbackDays: number = 30) {
    return request<{
      tenant_id: string;
      records_analyzed: number;
      recommendations: {
        type: string;
        rule: {
          id: string;
          when: { field: string; op: string; value: unknown }[];
          score_delta: number;
          tags: string[];
          description: string;
        };
        precision: number;
        coverage: number;
        support: number;
        quality_score: number;
      }[];
    }>("/api/decisions/v1/recommendations/generate", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, lookback_days: lookbackDays }),
    });
  },

  preview(tenantId: string, rule: unknown) {
    return request<{
      records_tested: number;
      affected: number;
      decisions_would_change: number;
      impact_rate: number;
    }>("/api/decisions/v1/recommendations/preview", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, rule }),
    });
  },

  analyze(body: { tenant_id: string; limit?: number; max_rules?: number; min_confidence?: number }) {
    return request<{
      tenant_id: string;
      records_analyzed: number;
      fraud_rate: number;
      insights: Array<{
        feature: string;
        importance: number;
        fraud_mean: number;
        legit_mean: number;
        suggested_threshold: number | null;
        suggested_op: string;
        description: string;
      }>;
      recommendations: Array<{
        rule_id: string;
        description: string;
        conditions: Array<{ field: string; op: string; value: unknown }>;
        suggested_score_delta: number;
        suggested_tags: string[];
        confidence: number;
        support: number;
        precision: number;
        recall: number;
        lift: number;
      }>;
    }>("/api/decisions/v1/recommendations/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};

// ── Simulation (decision-api :8000) ─────────────────────────────────

export const simulation = {
  scenarios() {
    return request<{ scenarios: Record<string, unknown> }>("/api/decisions/v1/simulation/scenarios");
  },

  run(scenario: string, options?: { include_ml?: boolean }) {
    return request<{ result: unknown; sample_events: unknown[]; sample_decisions: unknown[] }>(
      "/api/decisions/v1/simulation/run",
      { method: "POST", body: JSON.stringify({ scenario, ...options }) },
    );
  },

  abTest(body: { scenario: string; rule_set_a: unknown[]; rule_set_b: unknown[] }) {
    return request<unknown>("/api/decisions/v1/simulation/ab-test", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};

// ── Investigation (investigation-agent :8006) ───────────────────────

export const investigation = {
  chat(message: string, tenantId: string = "demo", analystId: string = "analyst-1", caseId?: string) {
    return request<{ reply: string; tool_calls?: unknown[] }>(
      "/api/investigation/v1/chat",
      {
        method: "POST",
        body: JSON.stringify({
          tenant_id: tenantId,
          analyst_id: analystId,
          case_id: caseId,
          messages: [{ role: "user", content: message }],
        }),
      },
    );
  },

  chatWithHistory(messages: { role: string; content: string }[], tenantId: string = "demo", analystId: string = "analyst-1", caseId?: string) {
    return request<{ reply: string; tool_calls?: unknown[] }>(
      "/api/investigation/v1/chat",
      {
        method: "POST",
        body: JSON.stringify({
          tenant_id: tenantId,
          analyst_id: analystId,
          case_id: caseId,
          messages,
        }),
      },
    );
  },
};

// ── Compliance (decision-api :8000) ─────────────────────────────────

export const compliance = {
  regions() {
    return request<{ regions: Record<string, unknown> }>("/api/decisions/v1/compliance/regions");
  },
  privacyProfile(tenantId: string, region: string) {
    return request<unknown>("/api/decisions/v1/compliance/privacy-profile", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, region }),
    });
  },
  dsarAccess(tenantId: string, entityId: string, region: string) {
    return request<unknown>("/api/decisions/v1/compliance/dsar/access", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, entity_id: entityId, region }),
    });
  },
  dsarErasure(tenantId: string, entityId: string, region: string, reason?: string) {
    return request<unknown>("/api/decisions/v1/compliance/dsar/erasure", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, entity_id: entityId, region, reason: reason || "" }),
    });
  },
  dsarPortability(tenantId: string, entityId: string, region: string) {
    return request<unknown>("/api/decisions/v1/compliance/dsar/portability", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, entity_id: entityId, region }),
    });
  },
  certifications() {
    return request<unknown>("/api/decisions/v1/compliance/certifications");
  },
};

// ── OSINT (integration-ingress :8000, /v1/osint) ────────────────────

export const osint = {
  enrich(body: { email?: string; phone?: string; ip?: string; domain?: string }) {
    return request<{
      composite_risk_score: number;
      risk_level: string;
      enrichments: Record<string, unknown>;
      signals_queried: number;
      elapsed_ms: number;
    }>("/api/ingress/v1/osint", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  sources() {
    return request<{ sources: Record<string, unknown[]>; total_sources: number }>("/api/ingress/v1/osint/sources");
  },
};

// ── Disputes (case-api :8002) ───────────────────────────────────────

export interface DisputeEntry {
  id: string;
  case_id: string | null;
  tenant_id: string;
  entity_id: string;
  trace_id: string;
  dispute_type: string;
  status: string;
  reason_code: string;
  amount: number;
  currency: string;
  merchant_id: string | null;
  card_network: string | null;
  original_decision: string | null;
  original_score: number | null;
  original_rule_hits: string[];
  original_ml_score: number | null;
  outcome: string | null;
  resolution_notes: string | null;
  filed_at: string | null;
  resolved_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DisputeStats {
  total: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  by_outcome: Record<string, number>;
  total_amount: number;
  win_rate: number;
}

export const disputes = {
  list(tenantId: string, params?: { status?: string; dispute_type?: string; entity_id?: string; limit?: number }) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    if (params?.status) q.set("status", params.status);
    if (params?.dispute_type) q.set("dispute_type", params.dispute_type);
    if (params?.entity_id) q.set("entity_id", params.entity_id);
    if (params?.limit) q.set("limit", String(params.limit));
    return request<{ items: DisputeEntry[] }>(`/api/cases/v1/disputes?${q}`);
  },

  get(disputeId: string) {
    return request<DisputeEntry>(`/api/cases/v1/disputes/${disputeId}`);
  },

  create(data: {
    tenant_id: string;
    entity_id: string;
    trace_id: string;
    dispute_type?: string;
    reason_code?: string;
    amount?: number;
    currency?: string;
    merchant_id?: string;
    card_network?: string;
    case_id?: string;
  }) {
    return request<DisputeEntry>("/api/cases/v1/disputes", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  update(disputeId: string, data: { status?: string; outcome?: string; resolution_notes?: string }) {
    return request<DisputeEntry>(`/api/cases/v1/disputes/${disputeId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  stats(tenantId: string) {
    return request<DisputeStats>(`/api/cases/v1/disputes/stats?tenant_id=${tenantId}`);
  },

  originalDecision(disputeId: string) {
    return request<{ dispute_id: string; trace_id: string; original_decision: Record<string, unknown> }>(
      `/api/cases/v1/disputes/${disputeId}/original-decision`,
    );
  },

  entityHistory(entityId: string, tenantId: string) {
    return request<{
      entity_id: string;
      total_disputes: number;
      fraud_confirmed_count: number;
      false_positive_count: number;
      total_disputed_amount: number;
      risk_indicator: string;
      disputes: DisputeEntry[];
    }>(`/api/cases/v1/disputes/entity/${entityId}/history?tenant_id=${tenantId}`);
  },
};

// ── Entity Lists (decision-api :8000) ───────────────────────────────

export interface ListEntryData {
  list_type: string;
  tenant_id: string;
  entity_id: string;
  reason: string;
  created_by: string;
  expires_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export const entityLists = {
  check(tenantId: string, entityId: string) {
    return request<{ found: boolean; list_type: string | null; action: string; reason: string }>(
      `/api/decisions/v1/lists/check/${tenantId}/${entityId}`,
    );
  },

  list(listType: string, tenantId: string, limit?: number) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    if (limit) q.set("limit", String(limit));
    return request<{ list_type: string; tenant_id: string; count: number; entries: ListEntryData[] }>(
      `/api/decisions/v1/lists/${listType}?${q}`,
    );
  },

  add(listType: string, data: {
    tenant_id: string;
    entity_id: string;
    reason?: string;
    created_by?: string;
    expires_at?: string | null;
    metadata?: Record<string, unknown>;
  }) {
    return request<ListEntryData>(`/api/decisions/v1/lists/${listType}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  remove(listType: string, tenantId: string, entityId: string) {
    return request<{ removed: boolean }>(
      `/api/decisions/v1/lists/${listType}/${tenantId}/${entityId}`,
      { method: "DELETE" },
    );
  },

  bulkAdd(listType: string, tenantId: string, entries: { entity_id: string; reason?: string }[]) {
    return request<{ added: number; entries: ListEntryData[] }>(
      `/api/decisions/v1/lists/${listType}/bulk`,
      { method: "POST", body: JSON.stringify({ tenant_id: tenantId, entries }) },
    );
  },

  stats(tenantId: string) {
    return request<{ tenant_id: string; stats: Record<string, number> }>(
      `/api/decisions/v1/lists/stats/${tenantId}`,
    );
  },
};
