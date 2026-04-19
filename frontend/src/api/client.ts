import type { AccessGroupId, AccessModuleId, ModuleCatalogEntry } from "../config/accessModuleCatalog";
import {
  type ConfidenceTier,
  type InferenceContext,
  type MlTopFactor,
  normalizeInferenceContext,
} from "./inferenceContext";
import { reportDataOutcome } from "./dataSourceState";
import { getMockResponse } from "./mockData";

export type { ConfidenceTier, InferenceContext, MlTopFactor };
export { normalizeInferenceContext };

const USE_API_MOCKS = (import.meta.env.VITE_USE_API_MOCKS as string | undefined)?.trim().toLowerCase() === "true";

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
  inference_context: InferenceContext;
  recommended_action?: string | null;
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
  /** May be partial; UI should pass through `normalizeInferenceContext`. */
  inference_context?: unknown;
  /** Ordered explainability rows persisted with audit snapshots (v1.2+). */
  explanation_drivers?: Array<{
    reason: string;
    category: string;
    label: string;
    rank: number;
    source: "driver_explain" | "driver_reasons";
  }>;
  recommended_action?: string | null;
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
  queue_score?: number;
  recommended_action?: string;
  comments?: Array<{ author: string; text: string; timestamp: string }>;
  sla_deadline?: string;
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
  description?: string;
  assigned_team?: string;
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
  model_name: string;
  version: number;
  traffic_weight: number;
  active: boolean;
  has_onnx: boolean;
  total_inferences: number;
  avg_latency_ms: number;
  metadata: Record<string, unknown>;
}

export interface CaseOpsKpis {
  tenant_id: string;
  total_cases: number;
  queue_score_avg: number;
  critical_open: number;
  investigating_rate: number;
  resolved_rate: number;
  median_case_age_hours: number;
  by_status?: Record<string, number>;
  sla_breached_open_or_investigating?: number;
  /** Cases with fraud/chargeback label boosts in queue score */
  label_boost_cases?: number;
}

export interface CaseDeskActivity {
  tenant_id: string;
  period_days: number;
  since: string;
  touch_actions_total: number;
  by_action: Record<string, number>;
  recent: Array<{
    id: string;
    action: string;
    actor: string;
    resource_id: string;
    created_at: string | null;
  }>;
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
  const allowMockFallback = USE_API_MOCKS;
  try {
    const res = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers as Record<string, string> | undefined) },
    });
    const text = await res.text();
    const ct = res.headers.get("content-type") ?? "";
    if (!res.ok) {
      if (allowMockFallback) {
        const mock = getMockResponse(url, init);
        if (mock !== null) {
          reportDataOutcome("mock");
          return mock as T;
        }
      }
      reportDataOutcome("offline");
      throw new Error(`${res.status} ${text || res.statusText}`);
    }
    if (!ct.includes("json") && !text.trimStart().startsWith("{") && !text.trimStart().startsWith("[")) {
      if (allowMockFallback) {
        const mock = getMockResponse(url, init);
        if (mock !== null) {
          reportDataOutcome("mock");
          return mock as T;
        }
      }
      reportDataOutcome("offline");
      throw new Error(
        `Expected JSON from ${url}, got ${ct || "unknown type"} (starts with: ${text.slice(0, 80).replace(/\s+/g, " ")}…)`,
      );
    }
    try {
      const parsed = JSON.parse(text) as T;
      reportDataOutcome("live");
      return parsed;
    } catch {
      if (allowMockFallback) {
        const mock = getMockResponse(url, init);
        if (mock !== null) {
          reportDataOutcome("mock");
          return mock as T;
        }
      }
      reportDataOutcome("offline");
      throw new Error(
        `Expected JSON from ${url}, got non-JSON response (starts with: ${text.slice(0, 80).replace(/\s+/g, " ")}…)`,
      );
    }
  } catch (err) {
    if (allowMockFallback) {
      const mock = getMockResponse(url, init);
      if (mock !== null) {
        reportDataOutcome("mock");
        return mock as T;
      }
    }
    reportDataOutcome("offline");
    throw err;
  }
}

// ── Decisions (decision-api :8000) ──────────────────────────────────

export const decisions = {
  evaluate(payload: DecisionRequest) {
    return request<DecisionResponse>("/api/decisions/v1/decisions/evaluate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getAudit(traceId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<AuditEntry>(`/api/decisions/v1/audit/${traceId}?${q}`);
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

  challengePolicies() {
    return request<{
      policies: Array<{ policy_id: string; version: number; description: string }>;
    }>("/api/decisions/v1/challenge-policies");
  },

  governance() {
    return request<{
      inference_schema_version: string;
      rule_packs: {
        active_pack_count: number;
        shadow_pack_count: number;
        packs: Array<{
          file: string | undefined;
          name: unknown;
          mode: unknown;
          canary_percent: unknown;
          effective_at: unknown;
          approved_by: unknown;
          rule_count: number;
        }>;
      };
      experiment_registry_lines: number;
      drift_smoke: { script: string; note: string };
    }>("/api/decisions/v1/ops/governance");
  },

  counterCatalog() {
    return request<{
      catalog_version: string;
      manifest_version?: string;
      redis_key_version?: string | null;
      counters: Array<Record<string, unknown>>;
    }>("/api/decisions/v1/internal/counters/catalog");
  },

  calibrationStatus(tenantId: string, profile: string = "default") {
    const q = new URLSearchParams({ tenant_id: tenantId, profile });
    return request<{
      tenant_id: string;
      profile: string;
      inference_schema_version: string;
      challenge_policy_default?: string;
      calibration: Record<string, unknown>;
    }>(`/api/decisions/v1/ops/calibration-status?${q}`);
  },

  calibrationDrift(tenantId: string, profile: string = "default") {
    const q = new URLSearchParams({ tenant_id: tenantId, profile });
    return request<Record<string, unknown>>(`/api/decisions/v1/calibration/drift?${q}`);
  },

  calibrationSummary(tenantId: string, profile: string = "default", limit: number = 15) {
    const q = new URLSearchParams({ tenant_id: tenantId, profile, limit: String(limit) });
    return request<{
      tenant_id: string;
      profile: string;
      snapshots: Array<Record<string, unknown>>;
    }>(`/api/decisions/v1/calibration/summary?${q}`);
  },
};

// ── Feature service (velocity + parity verify) — proxied as /api/features ─

const _featureHeaders = (): HeadersInit => {
  const h: Record<string, string> = {};
  const key = (import.meta.env.VITE_FEATURE_SERVICE_API_KEY as string | undefined)?.trim();
  if (key) h["x-api-key"] = key;
  return h;
};

export const features = {
  health() {
    return request<{ status?: string }>("/api/features/v1/health");
  },

  velocityQuery(body: { tenant_id: string; entity_id: string; payload?: Record<string, unknown> }) {
    return request<{
      tenant_id: string;
      entity_id: string;
      velocity_counters: Record<string, unknown>;
      velocity_key_order: string[];
    }>("/api/features/v1/velocity/query", {
      method: "POST",
      headers: { "Content-Type": "application/json", ..._featureHeaders() },
      body: JSON.stringify({
        tenant_id: body.tenant_id,
        entity_id: body.entity_id,
        payload: body.payload ?? {},
      }),
    });
  },

  parityVerify(body: {
    tenant_id: string;
    entity_id: string;
    payload?: Record<string, unknown>;
    expected: Record<string, number>;
    epsilon?: number;
  }) {
    return request<{
      ok: boolean;
      tenant_id: string;
      entity_id: string;
      epsilon: number;
      checked_keys: string[];
      drift: Record<string, unknown>;
      live_sample: Record<string, unknown>;
    }>("/api/features/v1/internal/parity/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json", ..._featureHeaders() },
      body: JSON.stringify({
        tenant_id: body.tenant_id,
        entity_id: body.entity_id,
        payload: body.payload ?? {},
        expected: body.expected,
        epsilon: body.epsilon ?? 0.5,
      }),
    });
  },
};

// ── Event ingest (event-ingest :8007) — proxied as /api/ingest ───────

export const ingest = {
  /** Contract reject tallies since process boot. */
  ingestStats() {
    return request<{
      service: string;
      since: string;
      contract_reject_by_reason: Record<string, number>;
      total_contract_rejects: number;
      envelope_mode?: string;
      require_idempotency_key?: boolean;
      note?: string;
    }>("/api/ingest/v1/ingest/stats");
  },
};

// ── Cases (case-api :8002) ──────────────────────────────────────────

export const cases = {
  list(params: { tenant_id: string; status?: string; limit?: number; sort_by?: "queue" | "updated" | "priority" }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.status) q.set("status", params.status);
    if (params.limit) q.set("limit", String(params.limit));
    if (params.sort_by) q.set("sort_by", params.sort_by);
    return request<{ items: Case[] }>(`/api/cases/v1/cases?${q}`);
  },

  get(caseId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<Case>(`/api/cases/v1/cases/${caseId}?${q}`);
  },

  create(data: CaseCreateRequest) {
    return request<Case>("/api/cases/v1/cases", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  update(
    caseId: string,
    tenantId: string,
    data: Partial<Pick<Case, "status" | "priority" | "assigned_team" | "title">>,
  ) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<Case>(`/api/cases/v1/cases/${caseId}?${q}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  addComment(caseId: string, tenantId: string, author: string, body: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{ ok: boolean }>(`/api/cases/v1/cases/${caseId}/comments?${q}`, {
      method: "POST",
      body: JSON.stringify({ author, body }),
    });
  },

  addLabels(caseId: string, tenantId: string, labels: string[]) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{ ok: boolean; labels: string[] }>(
      `/api/cases/v1/cases/${caseId}/labels?${q}`,
      { method: "POST", body: JSON.stringify({ labels }) },
    );
  },

  getSla(caseId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{
      case_id: string;
      priority: string;
      sla_deadline: string;
      breached: boolean;
      status: string;
    }>(`/api/cases/v1/cases/${caseId}/sla?${q}`);
  },

  getAudit(caseId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{ history: unknown[] }>(`/api/cases/v1/cases/${caseId}/audit?${q}`);
  },

  evidenceBundle(caseId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<Record<string, unknown>>(`/api/cases/v1/cases/${caseId}/evidence-bundle?${q}`);
  },

  generateSar(caseId: string, tenantId: string, format: string = "fincen_xml") {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<unknown>(`/api/cases/v1/cases/${caseId}/sar/generate?${q}`, {
      method: "POST",
      body: JSON.stringify({ format }),
    });
  },

  bulkUpdate(data: {
    tenant_id: string;
    case_ids: string[];
    status?: string;
    priority?: string;
    assigned_team?: string;
    add_labels?: string[];
  }) {
    return request<{ updated: number; items: Case[] }>("/api/cases/v1/cases/bulk-update", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  playbooks() {
    return request<{ playbooks: Record<string, Record<string, unknown>> }>("/api/cases/v1/cases/playbooks");
  },

  applyPlaybook(caseId: string, tenantId: string, playbookId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{ ok: boolean; playbook: string; case: Case }>(
      `/api/cases/v1/cases/${caseId}/playbooks/${playbookId}?${q}`,
      { method: "POST" },
    );
  },

  listViews(tenantId: string) {
    return request<{ items: Array<{ name: string; tenant_id: string; filters: Record<string, unknown> }> }>(
      `/api/cases/v1/case-views?tenant_id=${tenantId}`,
    );
  },

  saveView(data: { tenant_id: string; name: string; filters: Record<string, unknown> }) {
    return request<{ ok: boolean; view: { name: string } }>(
      "/api/cases/v1/case-views",
      { method: "POST", body: JSON.stringify(data) },
    );
  },

  deleteView(name: string, tenantId: string) {
    return request<{ removed: boolean }>(
      `/api/cases/v1/case-views/${encodeURIComponent(name)}?tenant_id=${tenantId}`,
      { method: "DELETE" },
    );
  },

  opsKpis(tenantId: string) {
    return request<CaseOpsKpis>(`/api/cases/v1/cases/ops/kpis?tenant_id=${tenantId}`);
  },

  cohortCompare(tenantId: string, periodDays: number = 7) {
    const q = new URLSearchParams({ tenant_id: tenantId, period_days: String(periodDays) });
    return request<{
      tenant_id: string;
      period_days: number;
      cases_created_recent: number;
      cases_created_prior: number;
      delta: number;
      delta_percent_vs_prior: number | null;
    }>(`/api/cases/v1/cases/analytics/cohort-compare?${q}`);
  },

  deskActivity(tenantId: string, periodDays: number = 7, limit: number = 40) {
    const q = new URLSearchParams({
      tenant_id: tenantId,
      period_days: String(periodDays),
      limit: String(limit),
    });
    return request<CaseDeskActivity>(`/api/cases/v1/cases/ops/desk-activity?${q}`);
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
  health() {
    return request<{
      status: string;
      disable_ml?: boolean;
      model_version?: string;
      onnx_loaded?: boolean;
      registry_models?: number;
      shap_stretch_enabled?: boolean;
    }>("/api/ml/v1/health");
  },

  models() {
    return request<{ models: ModelInfo[] }>("/api/ml/v1/models");
  },

  modelStats(modelName: string) {
    return request<{ model: string; versions: unknown }>(
      `/api/ml/v1/models/${modelName}/stats`,
    );
  },

  approve(modelName: string, version: number, approvedBy: string, stage: string = "approved") {
    return request<{ ok: boolean }>(`/api/ml/v1/models/${modelName}/approve`, {
      method: "POST",
      body: JSON.stringify({ version, approved_by: approvedBy, stage }),
    });
  },

  activate(modelName: string, version: number) {
    return request<{ ok: boolean }>(`/api/ml/v1/models/${modelName}/activate`, {
      method: "POST",
      body: JSON.stringify({ version }),
    });
  },

  setTrafficSplit(modelName: string, weights: Record<number, number>) {
    return request<{ ok: boolean }>(`/api/ml/v1/models/${modelName}/traffic-split`, {
      method: "POST",
      body: JSON.stringify({ weights }),
    });
  },

  rollback(modelName: string) {
    return request<{ ok: boolean }>(`/api/ml/v1/models/${modelName}/rollback`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  modelLineage(modelName: string, version: number) {
    return request<{
      ok: boolean;
      model: string;
      version: number;
      lineage: {
        sha256: string;
        signed_payload: Record<string, unknown>;
      };
    }>(`/api/ml/v1/models/${modelName}/${version}/lineage`);
  },
};

// ── Rules (decision-api :8000, /v1/rules router) ────────────────────

const _ruleActorHeaders = (): HeadersInit => {
  const h: Record<string, string> = {
    "X-Actor": (typeof localStorage !== "undefined" && localStorage.getItem("tarka.rule_actor")) || "web-ui",
  };
  const gov =
    typeof localStorage !== "undefined" ? localStorage.getItem("tarka.rule_governance_secret")?.trim() : "";
  if (gov) {
    h["X-Rule-Governance-Secret"] = gov;
  }
  return h;
};

export const rules = {
  list() {
    return request<{ packs: RulePack[] }>("/api/decisions/v1/rules");
  },

  changeLog(limit: number = 50) {
    return request<{ items: Array<{ ts: string; action: string; file: string; actor: string; detail?: unknown }> }>(
      `/api/decisions/v1/rules/change-log?limit=${limit}`,
    );
  },

  telemetry() {
    return request<{
      since_unix: number;
      total_hits: number;
      unique_keys: number;
      rows: Array<{ pack_file: string; rule_id: string; kind: string; hits: number }>;
    }>("/api/decisions/v1/rules/telemetry");
  },

  create(data: { name: string; rules?: unknown[]; tag_rules?: unknown[] }) {
    return request<unknown>("/api/decisions/v1/rules", {
      method: "POST",
      headers: _ruleActorHeaders(),
      body: JSON.stringify(data),
    });
  },

  update(filename: string, data: { name: string; rules: unknown[]; tag_rules?: unknown[] }) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}`, {
      method: "PUT",
      headers: _ruleActorHeaders(),
      body: JSON.stringify(data),
    });
  },

  deletePack(filename: string) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}`, {
      method: "DELETE",
      headers: _ruleActorHeaders(),
    });
  },

  addRule(filename: string, rule: unknown) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}/rules`, {
      method: "POST",
      headers: _ruleActorHeaders(),
      body: JSON.stringify(rule),
    });
  },

  deleteRule(filename: string, ruleId: string) {
    return request<unknown>(`/api/decisions/v1/rules/${filename}/rules/${ruleId}`, {
      method: "DELETE",
      headers: _ruleActorHeaders(),
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

  verticalPacks() {
    return request<{ vertical_packs: Record<string, { name: string; rules: number; version: number }> }>(
      "/api/decisions/v1/rules/vertical-packs",
    );
  },

  installVerticalPack(verticalName: string, overwrite: boolean = false) {
    return request<{ installed: string; vertical: string; rules: number }>(
      `/api/decisions/v1/rules/vertical-packs/${verticalName}/install?overwrite=${overwrite ? "true" : "false"}`,
      { method: "POST", headers: _ruleActorHeaders() },
    );
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
        headers: _ruleActorHeaders(),
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

  benchmarkVertical(body: { scenario: string; vertical: string }) {
    return request<{
      scenario: string;
      vertical: string;
      baseline: Record<string, unknown>;
      vertical_pack: Record<string, unknown>;
      delta: Record<string, unknown>;
    }>("/api/decisions/v1/simulation/benchmark/vertical", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};

// ── Investigation (investigation-agent :8006) ───────────────────────

/** Mirrors investigation-agent; server enforces track_historical_actions (drops audit if false). */
export interface InvestigationContextOptions {
  track_historical_actions: boolean;
  only_session: boolean;
  skip_session_actions: boolean;
  /** ISO-8601 — when only_session is true, used for logging / prompt notes. */
  session_started_at?: string | null;
}

export interface InvestigationChatOpts {
  platform_audit?: PlatformAuditEvent[];
  context_options?: InvestigationContextOptions;
  /** From POST /v1/batch/ingest — enables tabular batch tools in the agent. */
  batch_id?: string | null;
  /** Built-in workflow template from GET /v1/playbooks. */
  playbook_id?: string | null;
}

export interface InvestigationBatchIngestResponse {
  batch_id: string;
  filename: string;
  format: string;
  row_count: number;
  columns: string[];
  sample_rows: Record<string, unknown>[];
  limits?: Record<string, unknown>;
}

export interface InvestigationGovernanceInfo {
  profile: string;
  label: string;
  references: string[];
  batch_ttl_seconds: number;
  disclaimer: string;
}

/** Parsed from model trailer; server always returns at least one claim (fallback = unknown). */
export interface InvestigationClaim {
  text: string;
  source: "tool" | "unknown";
}

/** One row per tool invocation — mirrors investigation-agent `build_source_reference_cards`. */
export interface InvestigationSourceRefCard {
  tool: string;
  ok: boolean;
  case_id?: string;
  entity_id?: string;
  trace_id?: string;
  batch_id?: string;
  error?: string;
}

export interface InvestigationPlaybookEntry {
  id: string;
  title: string;
  vertical: string;
}

export interface InvestigationPlaybooksResponse {
  playbooks: InvestigationPlaybookEntry[];
}

export interface InvestigationAnswerSections {
  preamble?: string;
  facts_from_tools?: string;
  inferences?: string;
  unknowns?: string;
  next_steps?: string;
  sections_found?: string[];
}

export interface InvestigationClaimSupportRow {
  claim_index: number;
  supported: boolean;
  method: string;
  hint?: string[] | null;
}

export interface InvestigationEvidenceBundleDraft {
  schema_hint?: string;
  generated_at?: string;
  turn_id?: string;
  prompt_version?: string;
  playbook_id?: string | null;
  narrative?: { reply?: string };
  structured_sections?: Record<string, unknown>;
  claims?: InvestigationClaim[];
  claims_analysis?: InvestigationClaimSupportRow[];
  source_refs?: InvestigationSourceRefCard[];
  tool_invocation_count?: number;
}

export interface InvestigationEvidenceSummaryResponse {
  tenant_id: string;
  analyst_id: string;
  case_id?: string | null;
  summary: string;
  confidence_label: "high" | "medium" | "low";
  citations: Array<{
    type: "trace_id" | "case_id" | "entity_id" | "artifact";
    value: string;
    source_tool?: string;
  }>;
  based_on: {
    source_ref_count: number;
    claim_count: number;
    supported_claim_count: number;
    tool_error_count: number;
  };
}

export interface InvestigationChatResponse {
  reply: string;
  tool_calls?: unknown[];
  claims: InvestigationClaim[];
  /** Structured “what the copilot touched” for audit UI. */
  source_refs?: InvestigationSourceRefCard[];
  /** Present when a server playbook was applied this turn. */
  playbook_id?: string;
  turn_id?: string;
  prompt_version?: string;
  answer_sections?: InvestigationAnswerSections;
  /** Server-side token overlap check per claim (not legal proof). */
  claims_deterministic_support?: InvestigationClaimSupportRow[];
  tool_acknowledgment_warnings?: string[];
  judge_assessments?: unknown;
  judge_error?: string;
  evidence_bundle_draft?: InvestigationEvidenceBundleDraft;
  claims_warning?: string;
  /** Present when server downgraded ungrounded tool-sourced claims. */
  claims_grounding_adjustments?: string[];
  warning?: string;
  /** True when injection heuristics matched under sanitize policy (request continued). */
  injection_sanitized?: boolean;
}

export const investigation = {
  chat(
    message: string,
    tenantId: string = "demo",
    analystId: string = "analyst-1",
    caseId?: string,
    opts?: InvestigationChatOpts,
  ) {
    const payload: Record<string, unknown> = {
      tenant_id: tenantId,
      analyst_id: analystId,
      case_id: caseId,
      messages: [{ role: "user", content: message }],
    };
    if (opts?.platform_audit?.length) {
      payload.platform_audit = opts.platform_audit.slice(0, 40);
    }
    if (opts?.context_options) {
      payload.context_options = opts.context_options;
    }
    if (opts?.batch_id) {
      payload.batch_id = opts.batch_id;
    }
    if (opts?.playbook_id) {
      payload.playbook_id = opts.playbook_id;
    }
    return request<InvestigationChatResponse>("/api/investigation/v1/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  chatWithHistory(
    messages: { role: string; content: string }[],
    tenantId: string = "demo",
    analystId: string = "analyst-1",
    caseId?: string,
    opts?: InvestigationChatOpts,
  ) {
    const payload: Record<string, unknown> = {
      tenant_id: tenantId,
      analyst_id: analystId,
      case_id: caseId,
      messages,
    };
    if (opts?.platform_audit?.length) {
      payload.platform_audit = opts.platform_audit.slice(0, 40);
    }
    if (opts?.context_options) {
      payload.context_options = opts.context_options;
    }
    if (opts?.batch_id) {
      payload.batch_id = opts.batch_id;
    }
    if (opts?.playbook_id) {
      payload.playbook_id = opts.playbook_id;
    }
    return request<InvestigationChatResponse>("/api/investigation/v1/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listPlaybooks() {
    return request<InvestigationPlaybooksResponse>("/api/investigation/v1/playbooks");
  },

  governance() {
    return request<InvestigationGovernanceInfo>("/api/investigation/v1/governance");
  },

  async ingestKnowledgeMemo(
    title: string,
    body: string,
    tenantId: string = "demo",
    analystId: string = "analyst-1",
  ): Promise<{
    doc_id: string;
    title: string;
    ttl_hours: number;
    docs_stored_for_scope: number;
    embeddings_stored?: boolean;
  }> {
    return request("/api/investigation/v1/knowledge/ingest", {
      method: "POST",
      body: JSON.stringify({
        tenant_id: tenantId,
        analyst_id: analystId,
        title: title || "untitled",
        body,
      }),
    });
  },

  async submitFeedback(payload: {
    turn_id: string;
    rating: -1 | 0 | 1;
    note?: string;
    claim_indices?: number[];
    tenant_id?: string;
    analyst_id?: string;
    tags?: Record<string, unknown>;
  }): Promise<{ ok: boolean; stored?: boolean; feedback_id?: number }> {
    return request("/api/investigation/v1/feedback", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getFeedbackSummary(tenantId: string, days = 7) {
    const q = new URLSearchParams({ tenant_id: tenantId, days: String(days) });
    return request<{
      tenant_id: string;
      window_days: number;
      total: number;
      by_rating: Record<string, number>;
      avg_rating: number | null;
    }>(`/api/investigation/v1/feedback/summary?${q}`);
  },

  getFeedbackRecent(tenantId: string, limit = 50) {
    const q = new URLSearchParams({ tenant_id: tenantId, limit: String(limit) });
    return request<{
      items: Array<{
        id: number;
        turn_id: string;
        analyst_id: string;
        rating: number;
        note: string | null;
        claim_indices: number[] | null;
        created_at: number;
        case_id: string | null;
        playbook_id: string | null;
      }>;
    }>(`/api/investigation/v1/feedback/recent?${q}`);
  },

  evidenceSummary(payload: {
    tenant_id: string;
    analyst_id: string;
    case_id?: string;
    source_refs?: InvestigationSourceRefCard[];
    claims?: InvestigationClaim[];
    claims_deterministic_support?: InvestigationClaimSupportRow[];
    reply?: string;
  }) {
    return request<InvestigationEvidenceSummaryResponse>("/api/investigation/v1/evidence/summary", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * SSE stream: meta + text deltas + final structured tail. Rebuild reply from delta events or use final payload.
   */
  async chatWithHistoryStream(
    messages: { role: string; content: string }[],
    tenantId: string = "demo",
    analystId: string = "analyst-1",
    caseId?: string,
    opts?: InvestigationChatOpts,
    onEvent?: (ev: { type: string; payload: unknown }) => void,
  ): Promise<InvestigationChatResponse> {
    const payload: Record<string, unknown> = {
      tenant_id: tenantId,
      analyst_id: analystId,
      case_id: caseId,
      messages,
    };
    if (opts?.platform_audit?.length) payload.platform_audit = opts.platform_audit.slice(0, 40);
    if (opts?.context_options) payload.context_options = opts.context_options;
    if (opts?.batch_id) payload.batch_id = opts.batch_id;
    if (opts?.playbook_id) payload.playbook_id = opts.playbook_id;
    const url = "/api/investigation/v1/chat/stream";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${text || res.statusText}`);
    }
    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");
    const dec = new TextDecoder();
    let buf = "";
    let reply = "";
    let merged: Partial<InvestigationChatResponse> = { claims: [], source_refs: [] };
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const block of parts) {
        const line = block.trim();
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        try {
          const msg = JSON.parse(raw) as { type: string; payload: unknown };
          onEvent?.(msg);
          if (msg.type === "delta" && msg.payload && typeof msg.payload === "object") {
            const p = msg.payload as { text?: string };
            if (p.text) reply += p.text;
          }
          if (msg.type === "final" && msg.payload && typeof msg.payload === "object") {
            const p = msg.payload as Partial<InvestigationChatResponse> & { tool_calls_count?: number };
            merged = { ...merged, ...p };
            if (!merged.tool_calls?.length && typeof p.tool_calls_count === "number") {
              merged.tool_calls = [];
            }
          }
        } catch {
          /* ignore bad chunk */
        }
      }
    }
    return {
      reply: reply || (merged.reply as string) || "",
      ...merged,
      claims: (merged.claims as InvestigationClaim[]) ?? [],
    } as InvestigationChatResponse;
  },

  async ingestBatch(
    file: File,
    tenantId: string = "demo",
    analystId: string = "analyst-1",
  ): Promise<InvestigationBatchIngestResponse> {
    const fd = new FormData();
    fd.append("tenant_id", tenantId);
    fd.append("analyst_id", analystId);
    fd.append("file", file);
    const url = "/api/investigation/v1/batch/ingest";
    try {
      const res = await fetch(url, { method: "POST", body: fd });
      const text = await res.text();
      if (res.ok) {
        return JSON.parse(text) as InvestigationBatchIngestResponse;
      }
      if (USE_API_MOCKS) {
        const mock = getMockResponse(url, { method: "POST" });
        if (mock !== null) return mock as InvestigationBatchIngestResponse;
      }
      throw new Error(`${res.status} ${text || res.statusText}`);
    } catch (err) {
      if (USE_API_MOCKS) {
        const mock = getMockResponse(url, { method: "POST" });
        if (mock !== null) return mock as InvestigationBatchIngestResponse;
      }
      throw err instanceof Error ? err : new Error("Batch ingest failed");
    }
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
  decisionEvidence(tenantId: string, limit: number = 200) {
    return request<{
      tenant_id: string;
      exported_at: string;
      controls: Array<{ id: string; name: string; status: string }>;
      summary: Record<string, unknown>;
      evidence: Array<Record<string, unknown>>;
    }>(`/api/decisions/v1/compliance/evidence/controls?tenant_id=${tenantId}&limit=${limit}`);
  },
  caseEvidence(tenantId: string, limit: number = 200) {
    return request<{
      tenant_id: string;
      exported_at: string;
      controls: Array<{ id: string; name: string; status: string }>;
      summary: Record<string, unknown>;
      evidence: Array<Record<string, unknown>>;
    }>(`/api/cases/v1/compliance/evidence?tenant_id=${tenantId}&limit=${limit}`);
  },
  decisionEvidenceKeys() {
    return request<{ active_key_id: string; algorithm: string; rotation_supported: boolean }>(
      "/api/decisions/v1/compliance/evidence/keys",
    );
  },
  caseEvidenceKeys() {
    return request<{ active_key_id: string; algorithm: string; rotation_supported: boolean }>(
      "/api/cases/v1/compliance/evidence/keys",
    );
  },
  verifyDecisionEvidence(bundle: Record<string, unknown>) {
    return request<{ valid: boolean; active_key_id: string }>(
      "/api/decisions/v1/compliance/evidence/verify",
      {
        method: "POST",
        body: JSON.stringify({ bundle }),
      },
    );
  },
  verifyCaseEvidence(bundle: Record<string, unknown>) {
    return request<{ valid: boolean; active_key_id: string }>(
      "/api/cases/v1/compliance/evidence/verify",
      {
        method: "POST",
        body: JSON.stringify({ bundle }),
      },
    );
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

export interface IntegrationRequestRecord {
  id: string;
  tenant_id: string;
  requested_name: string;
  category: string;
  use_case: string;
  contact?: string;
  github_username?: string;
  status: "pending_approval" | "approved" | "rejected";
  requested_at?: string;
  github_issue_url?: string | null;
  approved_at?: string | null;
  approved_by?: string | null;
  approved_by_name?: string | null;
  rejected_at?: string | null;
  rejected_by?: string | null;
  rejection_reason?: string | null;
}

export const integrations = {
  catalog() {
    return request<{
      total_providers: number;
      categories: string[];
      providers: Array<{
        id: string;
        name: string;
        category: string;
        type: string;
        required_config_fields?: string[];
        doc_url: string;
      }>;
    }>("/api/ingress/v1/integrations/catalog");
  },
  installed(tenantId: string) {
    return request<{
      tenant_id: string;
      installed: Array<Record<string, unknown>>;
      count: number;
    }>(`/api/ingress/v1/integrations/installed?tenant_id=${tenantId}`);
  },
  readiness(tenantId: string) {
    return request<{
      tenant_id: string;
      readiness_score: number;
      covered_categories: number;
      total_categories: number;
      coverage: Record<string, { installed: boolean; count: number }>;
    }>(`/api/ingress/v1/integrations/readiness?tenant_id=${tenantId}`);
  },
  install(tenantId: string, providerId: string, config?: Record<string, unknown>) {
    return request<{ ok: boolean; integration: Record<string, unknown> }>("/api/ingress/v1/integrations/install", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, provider_id: providerId, config: config ?? {} }),
    });
  },
  uninstall(tenantId: string, providerId: string) {
    return request<{ ok: boolean }>("/api/ingress/v1/integrations/uninstall", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, provider_id: providerId }),
    });
  },
  testConnectivity(tenantId: string, providerId: string, config?: Record<string, unknown>) {
    return request<{
      provider_id: string;
      status: "pass" | "fail";
      latency_ms: number;
      missing_fields: string[];
      required_config_fields: string[];
    }>("/api/ingress/v1/integrations/test-connectivity", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, provider_id: providerId, config: config ?? undefined }),
    });
  },
  getConfig(tenantId: string, providerId: string) {
    return request<{
      tenant_id: string;
      provider_id: string;
      required_config_fields: string[];
      masked_config: Record<string, string>;
    }>(`/api/ingress/v1/integrations/config/${providerId}?tenant_id=${tenantId}`);
  },
  configure(tenantId: string, providerId: string, config: Record<string, unknown>) {
    return request<{ ok: boolean; masked_config: Record<string, string> }>("/api/ingress/v1/integrations/configure", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, provider_id: providerId, config }),
    });
  },
  healthMatrix(tenantId: string) {
    return request<{
      tenant_id: string;
      score: number;
      rows: Array<{ provider_id: string; status: string; latency_ms: number; missing_fields: string[] }>;
    }>(`/api/ingress/v1/integrations/health-matrix?tenant_id=${tenantId}`);
  },
  /** Submitted requests; `github_issue_url` is set only after admin approval. */
  listRequests(params?: { tenant_id?: string; status?: string }) {
    const q = new URLSearchParams();
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    if (params?.status) q.set("status", params.status);
    const suffix = q.toString() ? `?${q}` : "";
    return request<{ items: IntegrationRequestRecord[]; count: number }>(
      `/api/ingress/v1/integrations/requests${suffix}`,
    );
  },
  approveRequest(requestId: string, body?: { approver_id?: string; approver_name?: string }) {
    return request<{
      ok: boolean;
      github_issue_url?: string;
      already_approved?: boolean;
      request?: IntegrationRequestRecord;
      error?: string;
    }>(`/api/ingress/v1/integrations/requests/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    });
  },
  rejectRequest(requestId: string, body?: { reason?: string }) {
    return request<{ ok: boolean; request?: IntegrationRequestRecord; error?: string }>(
      `/api/ingress/v1/integrations/requests/${encodeURIComponent(requestId)}/reject`,
      { method: "POST", body: JSON.stringify(body ?? {}) },
    );
  },
  requestNew(body: {
    tenant_id: string;
    requested_name: string;
    category: string;
    use_case: string;
    contact?: string;
    github_username?: string;
  }) {
    return request<{
      ok: boolean;
      status: string;
      message?: string;
      request: IntegrationRequestRecord;
      github_issue_url?: string | null;
    }>("/api/ingress/v1/integrations/request", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  vaultKmsStatus() {
    return request<{
      provider: string;
      active_key_id: string;
      rotation_enabled: boolean;
      rotation_interval_seconds: number;
      config_valid: boolean;
      config_issues: string[];
    }>("/api/ingress/v1/vault/kms");
  },
  vaultRotationJobs() {
    return request<{
      jobs: Array<{
        id: string;
        status: string;
        old_key_id: string;
        new_key_id: string;
        processed: number;
        rotated: number;
        failed: number;
      }>;
    }>("/api/ingress/v1/vault/rotation-jobs");
  },
  slo() {
    return request<{
      service: string;
      availability_target: number;
      latency_target_ms_p95: number;
      error_budget_window_days: number;
      current: {
        kms_provider: string;
        rotation_jobs: number;
        rotation_failures: number;
      };
    }>("/api/ingress/v1/slo");
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

// ── Admin / RBAC / audit (prototype — mock or future admin-api) ─────

export type AuditFlagType =
  | "high_click_rate"
  | "low_aht_anomaly"
  | "high_entity_access"
  | "high_risk_rule_change"
  | "guardrail_bypass_attempt"
  | "core_config_change";

export interface PlatformAuditFlag {
  type: AuditFlagType;
  severity: "info" | "warning" | "high" | "critical";
  note: string;
}

export interface PlatformAuditEvent {
  id: string;
  ts: string;
  user_id: string;
  user_name: string;
  action: "query" | "view" | "change";
  resource: string;
  detail: string;
  ip: string;
  flags: PlatformAuditFlag[];
}

export interface AdminCatalogGroup {
  id: AccessGroupId;
  label: string;
  modules: ModuleCatalogEntry[];
}

export interface AdminUserAccess {
  user_id: string;
  name: string;
  email: string;
  role: string;
  allowed_modules: AccessModuleId[];
  last_login?: string;
  /** Optional hint from directory / IdP; UI also infers from modules via policy presets. */
  access_policy_id?: string;
  can_manage_access?: boolean;
}

export interface AdminActiveSession {
  session_id: string;
  user_id: string;
  user_name: string;
  email: string;
  current_route: string;
  last_activity: string;
  ip: string;
  clicks_last_5m: number;
  entities_touched_1h: number;
  case_actions_1h: number;
  avg_dwell_seconds: number;
}

export interface AdminApprovalVote {
  user_id: string;
  user_name: string;
  at: string;
}

export interface AdminPendingApproval {
  id: string;
  status: "pending" | "approved" | "rejected";
  requested_at: string;
  requested_by: string;
  requested_by_name: string;
  summary: string;
  risk_tier: "standard" | "high" | "core";
  required_approvals: number;
  target_user_id: string;
  target_user_name: string;
  proposed_allowed_modules: string[];
  previous_allowed_modules: string[];
  votes: AdminApprovalVote[];
  rejected_at?: string;
  rejected_by?: string;
}

export const admin = {
  catalog() {
    return request<{ groups: AdminCatalogGroup[] }>("/api/admin/v1/catalog");
  },

  overview() {
    return request<{
      active_sessions: number;
      audit_events_flagged: number;
      pending_approvals: number;
      users_configured: number;
    }>("/api/admin/v1/overview");
  },

  listUsersAccess() {
    return request<{ users: AdminUserAccess[] }>("/api/admin/v1/users/access");
  },

  updateUserAccess(
    userId: string,
    body: {
      allowed_modules: AccessModuleId[];
      requested_by?: string;
      requested_by_name?: string;
    },
  ) {
    return request<
      | { applied: true; user: AdminUserAccess }
      | { applied: false; pending_approval_id: string; message: string }
      | { ok: false; error: string }
    >(`/api/admin/v1/users/${userId}/access`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  sessions() {
    return request<{ items: AdminActiveSession[] }>("/api/admin/v1/sessions");
  },

  auditLog(params?: { flags_only?: boolean; user_id?: string }) {
    const q = new URLSearchParams();
    if (params?.flags_only) q.set("flags_only", "1");
    if (params?.user_id) q.set("user_id", params.user_id);
    const suffix = q.toString() ? `?${q}` : "";
    return request<{ items: PlatformAuditEvent[] }>(`/api/admin/v1/audit${suffix}`);
  },

  listApprovals() {
    return request<{ items: AdminPendingApproval[] }>("/api/admin/v1/approvals");
  },

  approveRequest(approvalId: string, body: { approver_id: string; approver_name: string }) {
    return request<{ ok: boolean; approval?: AdminPendingApproval; applied?: boolean; error?: string }>(
      `/api/admin/v1/approvals/${approvalId}/approve`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  rejectRequest(approvalId: string, body?: { approver_id?: string; reason?: string }) {
    return request<{ ok: boolean; approval?: AdminPendingApproval; error?: string }>(
      `/api/admin/v1/approvals/${approvalId}/reject`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },
};
