import type { AccessGroupId, AccessModuleId, ModuleCatalogEntry } from "../config/accessModuleCatalog";
import {
  type ConfidenceTier,
  type InferenceContext,
  type MlTopFactor,
  normalizeInferenceContext,
} from "./inferenceContext";
import {
  type SaarthiFeatureImportanceRequestBody,
  type SaarthiFeatureImportanceResponse,
} from "../lib/saarthi/featureImportance";
import { reportDataOutcome } from "./dataSourceState";
import { assertIntegrationSecretsTransportSecure } from "../utils/integrationSecretsTransport";

export type { ConfidenceTier, InferenceContext, MlTopFactor };
export { normalizeInferenceContext };

const IS_PRODUCTION_BUILD = import.meta.env.PROD === true;

const MOCK_MODE = ((import.meta.env.VITE_USE_API_MOCKS as string | undefined) ?? "auto").trim().toLowerCase();

if (IS_PRODUCTION_BUILD && MOCK_MODE === "true") {
  throw new Error("VITE_USE_API_MOCKS=true is forbidden in production builds.");
}

/**
 * Mock fallback policy (non-production bundles only):
 * - `VITE_USE_API_MOCKS=true`  -> allow fallback when not a production build
 * - `VITE_USE_API_MOCKS=false` -> never allow fallback
 * - `VITE_USE_API_MOCKS=auto` (default) -> allow in dev, never in production
 *
 * Production: mocks are disabled; mock helpers are loaded only via dynamic import so they are not in the main chunk.
 */
const USE_API_MOCKS =
  !IS_PRODUCTION_BUILD && (MOCK_MODE === "true" || (MOCK_MODE !== "false" && import.meta.env.DEV));

/** ``GET /v1/entities/{id}/deep-context`` — JanusGraph neighborhood + current risk snapshot. */
export interface GraphEntityDeepContext {
  entity_id: string;
  tenant_id: string;
  historical_transactions: Array<{
    external_id: string;
    trace_id?: unknown;
    amount?: unknown;
    currency?: unknown;
    decision?: unknown;
    ip?: unknown;
    occurred_at?: unknown;
  }>;
  ip_addresses: Array<{
    ip: string;
    source: string;
    last_seen?: unknown;
    event_count?: number;
  }>;
  risk_history: Array<{
    recorded_at: string;
    risk_score?: unknown;
    risk_factors?: unknown;
    source: string;
  }>;
}

/**
 * Fetches deep entity context; returns ``null`` on HTTP 404 (entity absent in graph DB).
 * Uses ``fetch`` so 404 is not treated as a generic request failure when mocks are off.
 */
async function fetchGraphEntityDeepContext(entityId: string, tenantId: string): Promise<GraphEntityDeepContext | null> {
  const q = new URLSearchParams({ tenant_id: tenantId });
  const url = `/api/graph/v1/entities/${encodeURIComponent(entityId)}/deep-context?${q}`;
  try {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
    });
    const text = await res.text();
    if (res.status === 404) {
      return null;
    }
    if (!res.ok) {
      if (USE_API_MOCKS) {
        const mock = await loadMockResponse(url);
        if (mock !== null) {
          const m = mock as { not_found?: boolean };
          if (m.not_found) return null;
          return mock as GraphEntityDeepContext;
        }
      }
      throw new Error(parseHttpErrorMessage(res.status, res.statusText, text, res.headers));
    }
    return JSON.parse(text) as GraphEntityDeepContext;
  } catch (err) {
    if (USE_API_MOCKS) {
      const mock = await loadMockResponse(url);
      if (mock !== null) {
        const m = mock as { not_found?: boolean };
        if (m.not_found) return null;
        return mock as GraphEntityDeepContext;
      }
    }
    throw err;
  }
}

async function loadMockResponse(url: string, init?: RequestInit): Promise<unknown | null> {
  if (IS_PRODUCTION_BUILD) {
    return null;
  }
  const { getMockResponse } = await import("./mockData");
  return getMockResponse(url, init);
}

// ── Types ────────────────────────────────────────────────────────────

/** Optional envelope for LLM/MCP agent context on `POST /v1/decisions/evaluate` (mirrors decision-api schema). */
export interface AgentContextRequest {
  agent_runtime_id?: string;
  agent_session_id?: string;
  agent_client?: {
    client_type?: string;
    oauth_client_id?: string;
    mcp_server_ids?: string[];
    manifest_hash?: string;
    tool_allowlist_hash?: string;
    sdk_version?: string;
  };
  human_control?: {
    hitl_required_for_event?: boolean;
    human_approval_received?: boolean;
    approver_entity_id?: string;
    maker_checker_satisfied?: boolean;
  };
  orchestration?: {
    turn_id?: string;
    tool_names_ordered?: string[];
    tool_sequence_digest?: string;
    tool_depth?: number;
    tool_retry_count?: number;
    plan_digest?: string;
    untrusted_content_sources?: string[];
  };
  integrity?: {
    prompt_injection_heuristic_flag?: boolean;
    cross_channel_mismatch_flag?: boolean;
    policy_denial_count_this_session?: number;
  };
}

export interface DecisionRequest {
  event_type: string;
  entity_id: string;
  tenant_id: string;
  session_id?: string;
  payload?: Record<string, unknown>;
  device_context?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  agent_context?: AgentContextRequest;
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

/** POST `/v1/replay` — re-score stored audit payloads with ad-hoc rules (Python matcher on decision-api). */
export type RuleReplayConditionPayload = { field: string; op?: string; value?: unknown };

export type RuleReplayRulePayload = {
  id?: string;
  when: RuleReplayConditionPayload[];
  tags?: string[];
  score_delta?: number;
  description?: string;
};

export type RuleReplayRequestPayload = {
  tenant_id: string;
  rules_override: RuleReplayRulePayload[];
  limit?: number;
  trace_ids?: string[];
};

export type RuleReplayResultRow = {
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
};

export type RuleReplayResponse = {
  tenant_id: string;
  events_evaluated: number;
  decisions_changed: number;
  results: RuleReplayResultRow[];
  missing_trace_ids: string[];
};

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
  /** Present when ``detail_level`` is ``analyst`` or ``full`` — evaluate DAG step rows. */
  step_trace?: unknown[];
  fallback_reason?: string | null;
  /** Present when ``detail_level`` is ``analyst`` or ``full`` — normalized evaluate body (transaction envelope). */
  evaluate_payload?: Record<string, unknown> | null;
  input_map?: Record<string, unknown> | null;
}

/** Compact row from ``GET /v1/audit/recent`` (decision-api / core mount). */
export type AuditRuleResult = "ALLOW" | "DENY" | "REVIEW" | "SHADOW_REVIEW";

export interface AuditRecentItem {
  trace_id: string;
  short_id: string;
  amount: number | null;
  currency: string | null;
  rule_result: AuditRuleResult;
  /** Model / integrity confidence in ``0..1`` when present. */
  ai_confidence: number | null;
  created_at: string | null;
}

export interface AuditRecentResponse {
  tenant_id: string;
  items: AuditRecentItem[];
}

/**
 * Keyset-paged decision audit slice for the explorer UI (`GET /v1/audit/explorer`).
 * Designed for keyset / opaque cursor semantics against ClickHouse or Postgres replicas.
 */
export interface AuditExplorerResponse {
  tenant_id: string;
  items: AuditRecentItem[];
  /** Pass to the next request until null (end of stream or scan budget exhausted). */
  next_cursor: string | null;
  /** Optional planner estimate — omit when unknown (billions of rows). */
  approx_total_rows?: number | null;
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
  /** Optional taxonomy for routing / workload analytics (when case-api persists it). */
  case_type?: string | null;
  labels: string[];
  queue_score?: number;
  recommended_action?: string;
  comments?: Array<{ author: string; text: string; timestamp: string }>;
  sla_deadline?: string;
  created_at: string;
  updated_at: string;
  /** Optional evidence-locker graph (nodes + links) when case-api forwards Postgres ``graph_snapshot`` JSONB. */
  graph_snapshot?: Record<string, unknown> | null;
}

export interface CaseComment {
  author: string;
  body: string;
  created_at: string;
}

export interface CaseApiHealthResponse {
  status: string;
  database_backend?: string;
  database_url?: string;
  database_fallback_active?: boolean;
  database_fallback_reason?: string | null;
  database_bootstrap_mode?: string;
}

export interface CaseGraphPayload {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  message?: string;
}

export interface CaseDecisionExplanationPayload {
  case_id: string;
  trace_id: string;
  entity_id: string;
  graph_decision_explanation?: Record<string, unknown> | null;
  source: string;
  decision?: string;
  score?: number;
}

/** SAR filing intent regulatory status (case-api `sar_filing_intents`). */
export type SarFilingIntentStatus =
  | "PENDING_REVIEW"
  | "APPROVED"
  | "FILED"
  | "SFTP_QUEUED"
  | "TRANSMITTED"
  | "ACKNOWLEDGED"
  | "FAILED";

export interface SarAuditLogEntry {
  id: string;
  from_status: string | null;
  to_status: string;
  actor: string | null;
  detail: Record<string, unknown>;
  stack_trace: string | null;
  created_at: string | null;
}

export interface SarFilingIntentDetail {
  id: string;
  status: SarFilingIntentStatus;
  sar_artifact_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  audit_log: SarAuditLogEntry[];
}

export interface SarFilingIntentsResponse {
  case_id: string;
  intents: SarFilingIntentDetail[];
}

/** ``GET /v1/cases/ops/sar-transport/board`` — Kanban columns from ``sar_filing_intents``. */
export interface SarTransportBoardCard {
  id: string;
  tenant_id: string;
  case_id: string;
  status: SarFilingIntentStatus;
  sar_artifact_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SarTransportBoardColumn {
  count: number;
  items: SarTransportBoardCard[];
}

export interface SarTransportBoardResponse {
  schema: string;
  tenant_id: string;
  status_mapping: Record<string, unknown>;
  columns: {
    pending: SarTransportBoardColumn;
    claimed: SarTransportBoardColumn;
    uploaded: SarTransportBoardColumn;
  };
  failed: SarTransportBoardColumn;
}

export interface SarForceSftpSyncResponse {
  ok: boolean;
  published: boolean;
  processed_one: boolean;
  cooldown_seconds: number;
}

/** ``GET .../sar/intents/{id}/detail`` — specialized SAR workspace (notes lock + FinCEN digest). */
export interface SarIntentDetailResponse {
  case_id: string;
  intent_id: string;
  status: SarFilingIntentStatus;
  sar_artifact_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  investigative_notes_html: string;
  /** True when status is TRANSMITTED or ACKNOWLEDGED (Uploaded). */
  notes_editor_locked: boolean;
  /** Present only when locked: SHA-256 hex of wire payload bytes. */
  fincen_submission_sha256_hex: string | null;
  audit_log: SarAuditLogEntry[];
}

export interface SarInvestigativeNotesPatchResponse {
  ok: boolean;
  intent_id: string;
  notes_editor_locked: boolean;
  investigative_notes_html: string;
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

export type MulePathHop = {
  role: "origin" | "mule" | "payout" | string;
  entity_id: string;
  label: string;
  node_type: string;
  account_id?: string | null;
  description?: string;
  referred_by?: string;
  beneficiary?: string;
  channel?: string;
  tags?: string[];
};

export type MulePathTransfer = {
  id: string;
  from_role: string;
  to_role: string;
  from_entity_id: string;
  to_entity_id: string;
  amount: number;
  currency: string;
  trace_id: string;
  timestamp: string;
  channel: string;
  status: string;
};

export type MulePathResponse = {
  tenant_id: string;
  path_id: string;
  updated_at: string;
  source?: string;
  hops: MulePathHop[];
  transfers: MulePathTransfer[];
  summary: {
    hop_count: number;
    total_outflow: number;
    payout_amount: number;
    mule_retained: number;
    currency: string;
    elapsed_hours: number;
    risk_flags: string[];
  };
};

export type PromoAbuseUserRow = {
  user_id: string;
  display_name: string;
  redemption_count: number;
  first_redeemed_at: string;
  last_redeemed_at: string;
  device_id: string;
  ip_hint?: string;
  order_total_usd?: number;
  flags?: string[];
};

export type PromoAbuseDailyPoint = {
  date: string;
  unique_users: number;
  redemptions: number;
};

export type PromoAbuseResponse = {
  tenant_id: string;
  coupon_code: string;
  updated_at: string;
  source?: string;
  window_days: number;
  summary: {
    unique_users: number;
    total_redemptions: number;
    distinct_devices: number;
    users_with_shared_device_flags: number;
    abuse_risk: "normal" | "elevated" | "critical" | string;
  };
  thresholds: {
    warn_unique_users: number;
    critical_unique_users: number;
  };
  signals: string[];
  daily_series: PromoAbuseDailyPoint[];
  users: PromoAbuseUserRow[];
};

export type SyntheticIdentitySignal = {
  risk: "low" | "medium" | "high" | string;
  label: string;
  detail: string;
  score: number;
};

export type SyntheticIdentityUserRow = {
  user_id: string;
  entity_id: string;
  display_name: string;
  email: string;
  risk_score: number;
  is_synthetic_identity: boolean;
  signals: {
    ip: SyntheticIdentitySignal;
    browser: SyntheticIdentitySignal;
    email: SyntheticIdentitySignal;
  };
  combo_flags: string[];
  detected_at: string;
};

export type SyntheticIdentityDetectorsResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  thresholds: { flag_score: number };
  summary: {
    scanned_users: number;
    flagged_users: number;
    triple_high_combos: number;
    avg_risk_score: number;
  };
  users: SyntheticIdentityUserRow[];
};

export type SellerIntegrityRow = {
  seller_id: string;
  display_name: string;
  store_slug: string;
  category: string;
  window_days: number;
  successful_deliveries: number;
  review_count: number;
  review_to_delivery_ratio: number;
  integrity_score: number;
  integrity_tier: "trusted" | "normal" | "warning" | "critical" | string;
  signals: string[];
  avg_rating: number;
  updated_at: string;
};

export type SellerIntegrityResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  window_days: number;
  thresholds: {
    healthy_ratio_min: number;
    healthy_ratio_max: number;
    warn_ratio_above: number;
    critical_ratio_above: number;
  };
  summary: {
    seller_count: number;
    at_risk_sellers: number;
    trusted_sellers: number;
    avg_integrity_score: number;
    median_review_to_delivery_ratio: number;
    total_deliveries: number;
    total_reviews: number;
  };
  signals: string[];
  sellers: SellerIntegrityRow[];
};

export type PayoutDelayConfig = {
  automation_enabled: boolean;
  mule_score_hold_threshold: number;
  janusgraph_property: string;
  hold_duration_hours_default: number;
};

export type PayoutDelayPayoutRow = {
  payout_id: string;
  tenant_id: string;
  entity_id: string;
  beneficiary_label: string;
  amount_usd: number;
  currency: string;
  channel: string;
  mule_score: number;
  mule_score_source: string;
  janusgraph_vertex_id: string;
  status: "pending" | "held" | "released" | string;
  hold_reason: string | null;
  held_at: string | null;
  held_by: string | null;
  created_at: string;
  scheduled_release_at: string | null;
};

export type PayoutDelayEvent = {
  event_id: string;
  event_type: string;
  payout_id: string;
  mule_score: number;
  threshold: number;
  timestamp: string;
  detail: string;
};

export type PayoutDelayResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  config: PayoutDelayConfig;
  summary: {
    pending_count: number;
    held_count: number;
    released_count: number;
    held_amount_usd: number;
    automation_active: boolean;
  };
  events: PayoutDelayEvent[];
  payouts: PayoutDelayPayoutRow[];
};

export type PayoutDelayReleaseResponse = {
  ok: boolean;
  release: { tenant_id: string; payout_id: string; released_at: string; released_by: string };
  board: PayoutDelayResponse;
};

export type SocialEngineeringAccountRow = {
  account_id: string;
  user_id: string;
  display_name: string;
  listing_id: string;
  listing_title: string;
  listing_value_usd: number;
  listing_posted_at: string;
  email_changed_at: string | null;
  password_changed_at: string | null;
  minutes_listing_to_email_change: number | null;
  minutes_listing_to_password_change: number | null;
  is_social_engineering_flag: boolean;
  signals: string[];
  risk_score: number;
};

export type SocialEngineeringMonitorResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  config: {
    high_value_listing_usd: number;
    credential_change_window_minutes: number;
    require_email_and_password_change: boolean;
  };
  summary: {
    scanned_accounts: number;
    flagged_accounts: number;
    high_value_threshold_usd: number;
    credential_window_minutes: number;
  };
  signals: string[];
  accounts: SocialEngineeringAccountRow[];
};

export type ReviewRingProduct = {
  product_id: string;
  title: string;
  category: string;
  seller_id: string;
};

export type ReviewRingMemberReview = {
  product_id: string;
  rating: number;
  reviewed_at: string;
};

export type ReviewRingMember = {
  user_id: string;
  display_name: string;
  shared_product_count: number;
  avg_rating_given: number;
  reviews: ReviewRingMemberReview[];
  first_shared_review_at: string;
  last_shared_review_at: string;
  device_id: string;
};

export type ReviewRingCluster = {
  cluster_id: string;
  shared_products: ReviewRingProduct[];
  shared_product_ids: string[];
  member_count: number;
  members: ReviewRingMember[];
  suspicion_score: number;
  signals: string[];
  detected_at: string;
};

export type ReviewRingClustersResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  rules: { shared_product_count: number; min_ring_size: number };
  summary: {
    cluster_count: number;
    users_in_rings: number;
    high_suspicion_clusters: number;
    largest_ring_size: number;
  };
  signals: string[];
  clusters: ReviewRingCluster[];
};

export type KycHandoverCaseRow = {
  case_id: string;
  tenant_id: string;
  subject_user_id: string;
  subject_email: string;
  display_name: string;
  case_title: string;
  kyc_status: string;
  documents_requested: string[];
  handover_status: string;
  email_sent_at: string | null;
  email_message_id: string | null;
  email_template_id: string | null;
  email_subject: string | null;
  amount_usd: number;
  priority: string;
};

export type KycHandoverBoardResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  email_template_id: string;
  default_documents_requested: string[];
  summary: {
    needs_more_id_count: number;
    pending_email_count: number;
    email_sent_count: number;
  };
  cases: KycHandoverCaseRow[];
};

export type KycHandoverSendResponse = {
  ok: boolean;
  error?: string;
  case_id?: string;
  tenant_id?: string;
  kyc_status?: string;
  email?: {
    message_id: string;
    sent_at: string;
    to: string;
    template_id: string;
    subject: string;
    analyst_note: string | null;
    documents_requested: string[];
    upload_deadline_hours: number;
  };
  handover?: KycHandoverCaseRow;
};

export type RegionalRiskSubRegion = {
  sub_region_id: string;
  country_code: string;
  country_name: string;
  label: string;
  attack_wave_score: number;
  attack_tier: string;
  signals: string[];
  incidents_24h: number;
  blacklisted: boolean;
  updated_at: string | null;
  updated_by: string | null;
  policy_effect: string;
};

export type RegionalRiskCountryGroup = {
  country_code: string;
  country_name: string;
  sub_regions: RegionalRiskSubRegion[];
  blacklisted_count: number;
};

export type RegionalRiskTogglesResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  thresholds: { attack_wave_warn: number; attack_wave_critical: number };
  summary: {
    sub_region_count: number;
    blacklisted_count: number;
    elevated_wave_count: number;
    critical_wave_count: number;
  };
  signals: string[];
  sub_regions: RegionalRiskSubRegion[];
  country_groups: RegionalRiskCountryGroup[];
};

export type RegionalRiskTogglePatchResponse = {
  ok: boolean;
  sub_region: RegionalRiskSubRegion;
  board: RegionalRiskTogglesResponse;
};

export type CommandCenterKpi = {
  id: string;
  label: string;
  value: number | string;
  delta: string;
  tone: string;
  route: string;
};

export type CommandCenterActionItem = {
  id: string;
  title: string;
  description: string;
  route: string;
  priority: string;
  module: string;
};

export type CommandCenterModuleTile = {
  id: string;
  title: string;
  route: string;
  module: string;
  metric_label: string;
  metric_value: string;
  tone: string;
};

export type CommandCenterQuickLink = {
  label: string;
  route: string;
  module: string;
  hint?: string;
};

export type CommandCenterResponse = {
  tenant_id: string;
  updated_at: string;
  source?: string;
  hero_kpis: CommandCenterKpi[];
  action_queue: CommandCenterActionItem[];
  modules: CommandCenterModuleTile[];
  quick_links: CommandCenterQuickLink[];
};

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
  gnn_beta?: Record<string, unknown> | null;
  /** JanusGraph / graph-service: explicit 1-hop degree when exposed (else parse risk_factors connectivity strings). */
  neighbors_1hop?: number;
  /** Wall-clock traversal timing when the API publishes it (ms). */
  graph_traversal_ms?: number;
}

export interface RingSuspicionResult {
  tenant_id: string;
  entity_id: string;
  suspicion_level: "low" | "medium" | "high";
  score: number;
  reasons: string[];
  ring_samples: Array<Record<string, unknown>>;
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

/** `GET /v1/analytics/scorecard` — compact decision + rule-hit summary (analytics-sink). */
export interface AnalyticsDecisionScorecard {
  tenant_id: string;
  window_days: number;
  total_events: number;
  deny_rate_pct: number;
  per_decision: Array<{
    decision: string;
    event_count: number;
    event_pct: number;
    avg_score: number;
    min_score: number;
    max_score: number;
  }>;
  top_rule_hits: Array<Record<string, unknown>>;
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

function parseErrorString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function parseHttpErrorMessage(status: number, statusText: string, text: string, headers: Headers): string {
  let detail = text.trim() || statusText || "Request failed";
  let code: string | null = null;
  let supportId = parseErrorString(headers.get("x-correlation-id")) ?? parseErrorString(headers.get("x-request-id"));
  if (text.trimStart().startsWith("{")) {
    try {
      const body = JSON.parse(text) as Record<string, unknown>;
      if (body && typeof body === "object") {
        const err = (body.error ?? null) as Record<string, unknown> | null;
        detail =
          parseErrorString(err?.message) ??
          parseErrorString(body.detail) ??
          parseErrorString(text) ??
          statusText;
        code = parseErrorString(err?.code);
        supportId =
          parseErrorString(err?.support_id) ??
          parseErrorString(body.support_id) ??
          supportId;
      }
    } catch {
      /* keep fallback detail */
    }
  }
  const normalizedDetail = detail.replace(/\s+/g, " ").slice(0, 220);
  const codeSuffix = code ? ` code=${code}` : "";
  const supportSuffix = supportId ? ` support_id=${supportId}` : "";
  return `${status} ${normalizedDetail}${codeSuffix}${supportSuffix}`;
}

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
        const mock = await loadMockResponse(url, init);
        if (mock !== null) {
          reportDataOutcome("mock");
          return mock as T;
        }
      }
      reportDataOutcome("offline");
      throw new Error(parseHttpErrorMessage(res.status, res.statusText, text, res.headers));
    }
    if (!ct.includes("json") && !text.trimStart().startsWith("{") && !text.trimStart().startsWith("[")) {
      if (allowMockFallback) {
        const mock = await loadMockResponse(url, init);
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
        const mock = await loadMockResponse(url, init);
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
      const mock = await loadMockResponse(url, init);
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

  getAudit(traceId: string, tenantId: string, opts?: { detail_level?: "minimal" | "analyst" | "full" }) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    if (opts?.detail_level) {
      q.set("detail_level", opts.detail_level);
    }
    return request<AuditEntry>(`/api/decisions/v1/audit/${encodeURIComponent(traceId)}?${q}`);
  },

  recentAudit(tenantId: string, limit: number = 50) {
    const q = new URLSearchParams({ tenant_id: tenantId, limit: String(limit) });
    return request<AuditRecentResponse>(`/api/decisions/v1/audit/recent?${q}`);
  },

  /**
   * High-volume audit explorer — cursor-based paging + optional substring filter on trace / short id.
   * Backend should avoid OFFSET scans at scale (use keyset on `(created_at, trace_id)`).
   */
  auditExplorer(opts: {
    tenant_id: string;
    limit?: number;
    cursor?: string | null;
    q?: string;
  }) {
    const q = new URLSearchParams({ tenant_id: opts.tenant_id });
    q.set("limit", String(Math.min(500, Math.max(1, opts.limit ?? 200))));
    if (opts.cursor) q.set("cursor", opts.cursor);
    if (opts.q?.trim()) q.set("q", opts.q.trim());
    return request<AuditExplorerResponse>(`/api/decisions/v1/audit/explorer?${q}`);
  },

  replay(body: RuleReplayRequestPayload) {
    return request<RuleReplayResponse>("/api/decisions/v1/replay", {
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

  /** OSS #36 — detection vs compliance posture + dependency hints for analyst banner. */
  evaluationPosture() {
    return request<EvaluationPostureResponse>("/api/decisions/v1/ops/evaluation-posture");
  },

  /** OSS #51 — in-process SLO snapshot (Redis/NATS connectivity flags). */
  slo() {
    return request<DecisionApiSloResponse>("/api/decisions/v1/slo");
  },
};

/** Headers for decision-api routes that require ``X-API-Key`` (same env as rule builder). */
export function decisionServiceApiKeyHeaders(): HeadersInit {
  const key = (import.meta.env.VITE_API_KEY as string | undefined)?.trim();
  if (!key) return {};
  return { "x-api-key": key };
}

/**
 * Execute a single gated ClickHouse DDL via admin ``POST /v1/feature-store/ddl/execute``.
 * Surfaces HTTP bodies and non-JSON success responses explicitly (no silent failures).
 */
export async function executeFeatureStoreDdl(sql: string): Promise<{ ok: boolean; executed: boolean }> {
  const url = "/api/decisions/v1/feature-store/ddl/execute";
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...decisionServiceApiKeyHeaders(),
    },
    body: JSON.stringify({ sql }),
  });
  const text = await res.text();
  if (!res.ok) {
    let detail = text.trim() || `HTTP ${res.status}`;
    try {
      const j = JSON.parse(text) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail)) detail = JSON.stringify(j.detail, null, 2);
      else if (j.detail && typeof j.detail === "object") detail = JSON.stringify(j.detail as Record<string, unknown>, null, 2);
    } catch {
      /* keep raw body */
    }
    throw new Error(detail);
  }
  let parsed: { ok?: boolean; executed?: boolean };
  try {
    parsed = JSON.parse(text) as { ok?: boolean; executed?: boolean };
  } catch {
    throw new Error(`Expected JSON success body; got non-JSON (starts with: ${text.slice(0, 160).replace(/\s+/g, " ")})`);
  }
  if (parsed.ok !== true) {
    throw new Error(`Unexpected success payload (expected ok: true): ${text.slice(0, 400)}`);
  }
  return { ok: true, executed: Boolean(parsed.executed) };
}

export const featureStore = {
  executeDdl: executeFeatureStoreDdl,
};

export interface DecisionApiSloResponse {
  service: string;
  availability_target_pct?: number;
  latency_target_ms_p95?: number;
  error_budget_window_days?: number;
  current?: {
    redis_connected?: boolean;
    nats_connected?: boolean;
    [key: string]: unknown;
  };
}

export interface EvaluationPostureResponse {
  service: string;
  deployment_tier: string;
  tenant_reliability_profile?: "strict" | "balanced" | "permissive";
  evaluation_mode: "detection" | "compliance" | string;
  compliance_posture: string;
  compliance_degraded: boolean;
  compliance_degraded_reasons: string[];
  typology_count: number;
  predicate_registry_version: number;
  predicate_registry_pin_match: boolean;
  dependencies: Array<{ id: string; ok: boolean; detail?: string }>;
  last_rules_reload_at: string | null;
  runbook_url: string;
  request_id?: string | null;
}

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

// ── Omni search (core-api root ``/v1/omni-search``) ───────────────────

export type OmniSearchEntity = {
  entity_id: string;
  tenant_id: string;
  label: string;
  subtitle?: string | null;
};

export type OmniSearchCase = {
  id: string;
  tenant_id: string;
  title: string;
  entity_id: string;
  trace_id: string;
  status: string;
  label: string;
  subtitle?: string | null;
};

export type OmniSearchRule = {
  rule_id: string;
  pack_file: string;
  pack_name: string;
  label: string;
  subtitle?: string | null;
};

export type OmniSearchResponse = {
  entities: OmniSearchEntity[];
  cases: OmniSearchCase[];
  rules: OmniSearchRule[];
};

/** Unified command-palette search (cases + entities + rules). */
export function omniSearch(params: { q: string; tenant_id?: string | null }, signal?: AbortSignal) {
  const q = new URLSearchParams();
  const qq = params.q.trim();
  if (qq) q.set("q", qq);
  const tid = (params.tenant_id ?? "").trim();
  if (tid) q.set("tenant_id", tid);
  const qs = q.toString();
  const url = qs ? `/api/core/v1/omni-search?${qs}` : `/api/core/v1/omni-search`;
  return request<OmniSearchResponse>(url, signal ? { signal } : undefined);
}

// ── Cases (case-api :8002) ──────────────────────────────────────────

export const cases = {
  health() {
    return request<CaseApiHealthResponse>("/api/cases/v1/health");
  },

  list(params: { tenant_id: string; status?: string; limit?: number; sort_by?: "queue" | "updated" | "priority" }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.status) q.set("status", params.status);
    if (params.limit != null) q.set("limit", String(params.limit));
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

  getGraph(caseId: string, tenantId: string, depth: number = 2) {
    const q = new URLSearchParams({ tenant_id: tenantId, depth: String(depth) });
    return request<CaseGraphPayload>(`/api/cases/v1/cases/${caseId}/graph?${q}`);
  },

  getDecisionExplanation(caseId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<CaseDecisionExplanationPayload>(`/api/cases/v1/cases/${caseId}/decision-explanation?${q}`);
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

  listSarFilingIntents(caseId: string, tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<SarFilingIntentsResponse>(`/api/cases/v1/cases/${caseId}/sar/intents?${q}`);
  },

  approveSarFilingIntent(caseId: string, tenantId: string, intentId: string, opts: { actor_id: string }) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{ sar_filing_intent_id: string; status: string }>(
      `/api/cases/v1/cases/${caseId}/sar/intents/${encodeURIComponent(intentId)}/approve?${q}`,
      { method: "POST", body: JSON.stringify({ actor_id: opts.actor_id }) },
    );
  },

  queueSarFilingSftp(caseId: string, tenantId: string, intentId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<{ sar_filing_intent_id: string; status: string }>(
      `/api/cases/v1/cases/${caseId}/sar/intents/${encodeURIComponent(intentId)}/queue-sftp?${q}`,
      { method: "POST" },
    );
  },

  getSarIntentDetail(caseId: string, tenantId: string, intentId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<SarIntentDetailResponse>(
      `/api/cases/v1/cases/${caseId}/sar/intents/${encodeURIComponent(intentId)}/detail?${q}`,
    );
  },

  patchSarIntentInvestigativeNotes(caseId: string, tenantId: string, intentId: string, body: { notes_html: string }) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<SarInvestigativeNotesPatchResponse>(
      `/api/cases/v1/cases/${caseId}/sar/intents/${encodeURIComponent(intentId)}/investigative-notes?${q}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  },

  bulkUpdate(data: {
    tenant_id: string;
    case_ids: string[];
    status?: string;
    priority?: string;
    assigned_team?: string;
    add_labels?: string[];
    /** Appended to every case in the batch (same text, one write per case on the server). */
    comment_body?: string;
    comment_author?: string;
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

  sarTransportBoard(tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<SarTransportBoardResponse>(`/api/cases/v1/cases/ops/sar-transport/board?${q}`);
  },

  forceSarTransportSftpSync() {
    return request<SarForceSftpSyncResponse>("/api/cases/v1/cases/ops/sar-transport/force-sftp-sync", {
      method: "POST",
      body: "{}",
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

  ringSuspicion(entityId: string, tenantId: string, minRingSize: number = 3) {
    return request<RingSuspicionResult>(
      `/api/graph/v1/analytics/ring-suspicion?entity_id=${entityId}&tenant_id=${tenantId}&min_ring_size=${minRingSize}`,
    );
  },

  /** Deep neighborhood context; ``null`` when the graph DB has no vertex for this entity (404). */
  entityDeepContext(entityId: string, tenantId: string) {
    return fetchGraphEntityDeepContext(entityId, tenantId);
  },

  /** ``GET /v1/investigation/mule-path`` — User A → mule → payout fund flow (Prompt 179). */
  mulePath(params: {
    tenant_id: string;
    origin_entity_id?: string;
    mule_entity_id?: string;
    payout_entity_id?: string;
  }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.origin_entity_id) q.set("origin_entity_id", params.origin_entity_id);
    if (params.mule_entity_id) q.set("mule_entity_id", params.mule_entity_id);
    if (params.payout_entity_id) q.set("payout_entity_id", params.payout_entity_id);
    return request<MulePathResponse>(`/api/ingress/v1/investigation/mule-path?${q}`);
  },
};

// ── Analytics (analytics-sink :8008) ────────────────────────────────

export const analytics = {
  decisions(params?: { tenant_id?: string; limit?: number }) {
    const q = new URLSearchParams();
    q.set("tenant_id", params?.tenant_id ?? "demo");
    if (params?.limit) q.set("limit", String(params.limit));
    return request<{ rows: unknown[]; total: number }>(`/api/analytics/v1/analytics/decisions?${q}`);
  },

  hourly(params?: { tenant_id?: string; days?: number }) {
    const q = new URLSearchParams();
    q.set("tenant_id", params?.tenant_id ?? "demo");
    if (params?.days != null) q.set("days", String(params.days));
    return request<{ rows: HourlyStat[] }>(`/api/analytics/v1/analytics/hourly?${q}`);
  },

  topEntities(params?: { tenant_id?: string; limit?: number; days?: number; decision?: string }) {
    const q = new URLSearchParams();
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.days != null) q.set("days", String(params.days));
    if (params?.decision) q.set("decision", params.decision);
    return request<{ decision: string; entities: TopEntity[] }>(
      `/api/analytics/v1/analytics/top-entities?${q}`,
    );
  },

  scorecard(params?: { tenant_id?: string; days?: number }) {
    const q = new URLSearchParams();
    q.set("tenant_id", params?.tenant_id ?? "demo");
    if (params?.days != null) q.set("days", String(params.days));
    return request<AnalyticsDecisionScorecard>(`/api/analytics/v1/analytics/scorecard?${q}`);
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

/** Session-only governance secret (never persisted; avoids clear-text storage in localStorage). */
let _sessionRuleGovernanceSecret = "";

/** Called from Rules UI when the secret field changes. */
export function syncRuleGovernanceSecret(value: string): void {
  _sessionRuleGovernanceSecret = value.trim();
}

const _ruleActorHeaders = (): HeadersInit => {
  const h: Record<string, string> = {
    "X-Actor": (typeof localStorage !== "undefined" && localStorage.getItem("tarka.rule_actor")) || "web-ui",
  };
  if (_sessionRuleGovernanceSecret) {
    h["X-Rule-Governance-Secret"] = _sessionRuleGovernanceSecret;
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

/** v2 rule engine — immutable ``fraud_rules`` AST snapshots (Rust-backed evaluate path). */
export type RuleAstVersionSummary = {
  version: number;
  is_active: boolean;
  rule_count: number;
  created_at: string | null;
  ast_hash: string;
};

export type RuleAstVersionsResponse = {
  versions: RuleAstVersionSummary[];
  active_version: number | null;
  source?: string;
};

export type RuleAstVersionDetail = RuleAstVersionSummary & {
  rules_payload: unknown[];
};

export type RuleAstRollbackResponse = {
  ok: boolean;
  active_version: number;
  rule_count: number;
  reloaded?: boolean;
};

export const ruleEngine = {
  listVersions() {
    return request<RuleAstVersionsResponse>("/api/rule-engine/v1/rules/versions");
  },

  versionDetail(version: number) {
    return request<RuleAstVersionDetail>(`/api/rule-engine/v1/rules/versions/${version}`);
  },

  rollback(version: number) {
    return request<RuleAstRollbackResponse>(`/api/rule-engine/v1/rules/rollback/${version}`, {
      method: "POST",
    });
  },

  reload() {
    return request<{ ok: boolean; count?: number }>("/api/rule-engine/v1/rules/reload", {
      method: "POST",
    });
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

  /** Full pack JSON as stored under ``rules_path`` (includes ``_file``). */
  getPack(filename: string) {
    return request<RulePack & Record<string, unknown>>(
      `/api/decisions/v1/rules/${encodeURIComponent(filename)}`,
    );
  },
};

/**
 * ``BacktestRequest`` in decision-api ``backtest_api.py`` — persisted and executed by ``run_backtest_job``.
 * Use ISO-8601 UTC strings for datetimes (e.g. ``2025-01-15T12:00:00.000Z``).
 */
export type BacktestJobRequestPayload = {
  tenant_id: string;
  start_time?: string | null;
  end_time?: string | null;
  rule_pack: Record<string, unknown>;
  clickhouse_max_execution_seconds: number;
};

export type BacktestJobEnqueueResponse = {
  job_id: string;
  status: string;
  tenant_id: string;
  window_start: string;
  window_end: string;
  rule_pack_fingerprint_sha256: string;
  analytics_table: string;
  wall_timeout_seconds: number;
  chunk_size: number;
};

/** ``metrics_json`` from ``run_backtest_job`` (final payload when job succeeds). */
export type BacktestChartSeriesPoint = {
  chunk_index: number;
  rows_processed: number;
  false_positive_rate: number;
  precision: number;
  recall: number;
};

export type BacktestJobMetrics = Record<string, unknown> & {
  chart_series?: BacktestChartSeriesPoint[];
  rows_processed?: number;
  true_positives?: number;
  false_positives?: number;
  false_negatives?: number;
  historical_allows?: number;
  false_positive_rate?: number;
  precision?: number;
  recall?: number;
  decision_agreement_rate?: number;
  hit_rate?: number;
  rule_fired_rows?: number;
};

export type BacktestJobStatusResponse = {
  job_id: string;
  tenant_id: string;
  status: string;
  window_start: string;
  window_end: string;
  analytics_table: string;
  rows_processed: number;
  rule_pack_fingerprint_sha256: string;
  metrics: BacktestJobMetrics | null;
  error_detail: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export const backtestJobs = {
  enqueue(body: BacktestJobRequestPayload, opts?: { timeoutMs?: number }) {
    const timeoutMs = opts?.timeoutMs ?? 60_000;
    const ac = new AbortController();
    const tid = window.setTimeout(() => ac.abort(), timeoutMs);
    return request<BacktestJobEnqueueResponse>("/api/decisions/v1/rules/backtest/jobs", {
      method: "POST",
      body: JSON.stringify(body),
      signal: ac.signal,
    }).finally(() => window.clearTimeout(tid));
  },

  get(jobId: string) {
    return request<BacktestJobStatusResponse>(
      `/api/decisions/v1/rules/backtest/jobs/${encodeURIComponent(jobId)}`,
    );
  },
};

/** ``PitParquetExportRequest`` / job responses from ``decision_api/ml_export_api.py``. */
export type PitParquetExportRequestPayload = {
  tenant_id: string;
  window_start: string;
  window_end: string;
  analytics_table?: string | null;
  chunk_size?: number;
  payload_json_keys?: string[] | null;
  dispute_outcome_allowlist?: string[] | null;
};

export type PitParquetExportResponsePayload = {
  rows_written: number;
  chunks_processed: number;
  local_path: string;
  artifact_uri: string;
  presigned_get_url?: string | null;
  pit_note?: string;
};

export type PitParquetJobStartResponse = {
  job_id: string;
  status: "PENDING";
};

export type PitParquetJobStatusResponse = {
  job_id: string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progress_pct: number;
  rows_written: number;
  chunks_processed: number;
  max_rows: number;
  error?: string | null;
  result?: PitParquetExportResponsePayload | null;
};

export const pitParquetMlExport = {
  startJob(body: PitParquetExportRequestPayload) {
    return request<PitParquetJobStartResponse>("/api/decisions/v1/ml/export/pit-parquet/jobs", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", ...decisionServiceApiKeyHeaders() },
    });
  },

  getJob(jobId: string) {
    return request<PitParquetJobStatusResponse>(
      `/api/decisions/v1/ml/export/pit-parquet/jobs/${encodeURIComponent(jobId)}`,
      { headers: { "Content-Type": "application/json", ...decisionServiceApiKeyHeaders() } },
    );
  },
};

// ── Shadow sidecar LLM (tools/shadow; Vite proxies /api/shadow-llm → :8742) ──

export type ShadowSidecarChatMessage = { role: "system" | "user" | "assistant"; content: string };

export type ShadowSidecarStreamEvent =
  | { type: "delta"; payload?: { text?: string } }
  | { type: "final"; payload?: Record<string, unknown> }
  | { type: "error"; payload?: { message?: string; code?: string } };

export const SHADOW_LLM_STREAM_URL = "/api/shadow-llm/chat/stream";

/**
 * POST SSE stream from the local Shadow sidecar (`text/event-stream`).
 * Uses fetch + ReadableStream (not EventSource) so the body can be aborted via `signal` (Stop / disconnect).
 */
export async function streamShadowLLMChat(
  body: {
    messages: ShadowSidecarChatMessage[];
    case_id?: string | null;
    persona_id?: string | null;
    thread_id?: string | null;
    thread_reset?: boolean;
  },
  opts: {
    signal?: AbortSignal;
    onEvent: (ev: ShadowSidecarStreamEvent) => void;
  },
): Promise<void> {
  const res = await fetch(SHADOW_LLM_STREAM_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: opts.signal,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseHttpErrorMessage(res.status, res.statusText, text, res.headers));
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");
  const dec = new TextDecoder();
  let buf = "";
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
        const msg = JSON.parse(raw) as ShadowSidecarStreamEvent;
        opts.onEvent(msg);
      } catch {
        /* ignore malformed SSE line */
      }
    }
  }
}

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
  /** Optional anchors for /v1/evidence/summary resolves_to (OSS #40). */
  rule_id?: string;
  typology_id?: string;
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

/** Matches investigation-agent `POST /v1/evidence/summary` JSON body. */
export interface InvestigationEvidenceResolutionRef {
  /** decision_trace | case | json_rule | typology */
  artifact: string;
  id: string;
}

export interface InvestigationEvidenceSummaryCitation {
  claim_index: number;
  text: string;
  source: string;
  supported?: boolean | null;
  confidence_label: string;
  /** Structured anchors to trace, case, rule, or typology ids (OSS #40). */
  resolves_to?: InvestigationEvidenceResolutionRef[];
}

export interface InvestigationEvidenceSummaryNextAction {
  id: string;
  label: string;
  confidence: string;
  /** read | automated_side_effect (latter only when allow-listed server-side). */
  kind: string;
  resolves_to?: InvestigationEvidenceResolutionRef[];
}

export interface InvestigationEvidenceSummaryResponse {
  summary: string;
  confidence_label: "high" | "medium" | "low";
  summary_confidence?: {
    level: string;
    score: number;
    notes: string[];
  };
  claim_confidence_summary?: {
    high: number;
    medium: number;
    low: number;
  };
  citations: InvestigationEvidenceSummaryCitation[];
  /** Present on investigation-agent builds with OSS #40; treat as empty when missing. */
  next_actions?: InvestigationEvidenceSummaryNextAction[];
  source_refs?: InvestigationSourceRefCard[];
  trace_id?: string | null;
  case_id?: string | null;
  turn_id?: string;
  prompt_version?: string;
  workflow_id?: string | null;
  persona?: string;
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
  /** Runtime capability tier for the turn (LLM/tool availability). */
  copilot_mode?: "full" | "tools_only_deterministic" | "read_only_summary" | "offline";
  /** Machine-readable degradation causes for audit-friendly UI banners. */
  degraded_reasons?: string[];
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
    trace_id?: string;
    turn_id?: string;
    reply?: string;
    claims?: InvestigationClaim[];
    source_refs?: InvestigationSourceRefCard[];
    claims_deterministic_support?: InvestigationClaimSupportRow[];
    answer_sections?: InvestigationAnswerSections;
    decision_audit?: Record<string, unknown> | null;
    typology_breakdown?: Array<Record<string, unknown>> | null;
    proposed_next_actions?: Array<Record<string, unknown>> | null;
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
      throw new Error(parseHttpErrorMessage(res.status, res.statusText, text, res.headers));
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
        const mock = await loadMockResponse(url, { method: "POST" });
        if (mock !== null) return mock as InvestigationBatchIngestResponse;
      }
      throw new Error(parseHttpErrorMessage(res.status, res.statusText, text, res.headers));
    } catch (err) {
      if (USE_API_MOCKS) {
        const mock = await loadMockResponse(url, { method: "POST" });
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

// ── Saarthi (investigation-agent :8006, /v1/saarthi) ─────────────────

export type {
  SaarthiFeatureImportanceItem,
  SaarthiFeatureImportanceRequestBody,
  SaarthiFeatureImportanceResponse,
} from "../lib/saarthi/featureImportance";
export { buildSaarthiFeatureImportanceRequest } from "../lib/saarthi/featureImportance";

export const saarthi = {
  featureImportance(body: SaarthiFeatureImportanceRequestBody, init?: RequestInit) {
    return request<SaarthiFeatureImportanceResponse>("/api/investigation/v1/saarthi/feature-importance", {
      method: "POST",
      body: JSON.stringify(body),
      ...init,
    });
  },
};

// ── OSINT (integration-ingress :8000, /v1/osint) ────────────────────

export type NatsSetuChannelHealth = "healthy" | "degraded" | "offline" | "unknown";

export type NatsSetuMonitorChannel = {
  kind: string;
  label: string;
  status: NatsSetuChannelHealth;
  last_latency_ms: number | null;
  jetstream_pending: number | null;
  requests_24h: number;
  errors_24h: number;
  last_error: string | null;
};

/** ``GET /v1/osint/nats-setu-monitor`` — VPN / email / phone OSINT lanes over NATS Setu. */
export type NatsSetuMonitorResponse = {
  tenant_id: string;
  updated_at: string;
  nats_connected: boolean;
  jetstream_enabled: boolean;
  setu_query_subject?: string;
  nats_url_hint?: string | null;
  channels: NatsSetuMonitorChannel[];
};

/** ``GET/PUT /v1/ops/failover-toggles`` — analyst graph/AI plane kill-switches. */
export type FailoverTogglesState = {
  graph_plane_disabled: boolean;
  ai_plane_disabled: boolean;
  graph_latency_ms_p95: number | null;
  ai_latency_ms_p95: number | null;
  updated_at: string;
  updated_by?: string | null;
  source?: string;
};

export type FailoverTogglesPayload = {
  graph_plane_disabled: boolean;
  ai_plane_disabled: boolean;
  actor_id?: string;
  reason?: string;
};

/** ``GET /v1/ops/system-benchmarking`` — latency probes vs sub-millisecond target (Prompt 178). */
export type SystemBenchmarkProbe = {
  id: string;
  label: string;
  plane: string;
  critical: boolean;
  target_ms: number;
  samples_ms: number[];
  sample_count: number;
  min_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  mean_ms: number | null;
  delta_p95_vs_target_ms: number | null;
  meets_sub_ms_target: boolean;
  status: "on_target" | "near_target" | "over_target" | "unavailable" | string;
  detail: string | null;
};

export type SystemBenchmarkingResponse = {
  updated_at: string;
  source?: string;
  target: {
    name: string;
    description: string;
    p95_target_ms: number;
    near_target_multiplier: number;
  };
  methodology: {
    sample_rounds: number;
    primary_metric: string;
    comparison: string;
  };
  probes: SystemBenchmarkProbe[];
  summary: {
    critical_probe_count: number;
    on_target_count: number;
    over_target_count: number;
    all_critical_on_target: boolean;
    worst_probe_id: string | null;
    worst_p95_ms: number | null;
  };
};

/** ``GET /v1/ops/system-health-hud`` — edge workstation RAM, Redis RTT, Ollama queue. */
export type SystemHealthHudResponse = {
  updated_at: string;
  source?: "live" | "mock" | string;
  host: {
    chip_model: string;
    ram_total_gb: number;
    ram_used_gb: number;
    ram_used_pct: number;
    memory_pressure: number | null;
  };
  redis: {
    reachable: boolean;
    latency_ms: number | null;
    endpoint_hint: string | null;
  };
  ollama: {
    reachable: boolean;
    queue_depth: number;
    model_loaded: string | null;
    base_url_hint?: string | null;
  };
};

/** ``GET /v1/ops/nats-dead-letter-office`` — peek JetStream ingest DLQ (non-destructive). */
export type NatsDeadLetterItem = {
  id: string;
  sequence: number;
  subject: string;
  received_at: string | null;
  kind: string;
  status_code: number | null;
  tenant_id: string | null;
  entity_id: string | null;
  event_type: string | null;
  nats_source_subject: string | null;
  preview: string;
  envelope: Record<string, unknown>;
};

/** ``GET /v1/ops/automated-backup-indicators`` — Postgres / JanusGraph last snapshot times. */
export type BackupStoreIndicator = {
  store: "postgres" | "janusgraph" | string;
  label: string;
  last_snapshot_at: string | null;
  age_seconds: number | null;
  status: "ok" | "warn" | "stale" | "unknown" | "missing";
  artifact_hint: string | null;
  size_bytes: number | null;
  source: string;
  schedule_hint: string;
};

export type MarketplaceSdkPlatform = {
  id: string;
  name: string;
  codename: string;
  description: string;
  default_scopes: string[];
  env_var: string;
};

export type MarketplaceSdkApiKeysCatalogResponse = {
  platforms: MarketplaceSdkPlatform[];
  allowed_scopes: string[];
};

export type MarketplaceSdkApiKeyRecord = {
  id: string;
  tenant_id: string;
  platform: string;
  label: string;
  key_prefix: string;
  scopes: string[];
  status: "active" | "revoked" | string;
  created_at: string | null;
  last_used_at: string | null;
  created_by: string | null;
  rate_limit?: {
    enabled: boolean;
    requests_per_minute: number;
    burst: number;
  };
};

/** ``GET /v1/marketplace/rate-limit-shields`` — per SDK API key throttle config (Prompt 176). */
export type MarketplaceRateLimitShieldConfig = {
  enabled: boolean;
  requests_per_minute: number;
  burst: number;
};

export type MarketplaceRateLimitShieldLive = {
  requests_in_window: number;
  remaining: number;
  throttled: boolean;
  throttled_until: string | null;
  rejected_total: number;
};

export type MarketplaceRateLimitShieldItem = {
  key_id: string;
  tenant_id: string;
  platform: string;
  label: string;
  key_prefix: string;
  status: string;
  shield: MarketplaceRateLimitShieldConfig;
  live: MarketplaceRateLimitShieldLive;
};

export type MarketplaceRateLimitShieldsResponse = {
  tenant_id: string;
  items: MarketplaceRateLimitShieldItem[];
  count: number;
  summary: { throttled: number; shields_enabled: number };
};

/** ``POST /v1/compliance/pii-field-reveal`` — audit-logged PII reveal/hide (Prompt 177). */
export type PiiFieldRevealAuditItem = {
  id: string;
  tenant_id: string;
  actor_id: string | null;
  action: "reveal" | "hide" | string;
  field_kind: string;
  field_path: string;
  context_type: string;
  context_id: string | null;
  value_fingerprint: string;
  masked_preview: string;
  created_at: string | null;
};

export type PiiFieldRevealAuditResponse = {
  tenant_id: string;
  items: PiiFieldRevealAuditItem[];
  count: number;
  summary: { reveals: number };
};

export type MarketplaceSdkApiKeysListResponse = {
  tenant_id: string;
  keys: MarketplaceSdkApiKeyRecord[];
  count: number;
};

export type MarketplaceSdkApiKeyCreateResponse = {
  ok: boolean;
  key: MarketplaceSdkApiKeyRecord;
  secret: string;
  warning?: string;
};

/** ``GET /v1/marketplace/webhook-logs`` — outgoing Block callbacks to marketplace clients. */
export type MarketplaceWebhookLogItem = {
  id: string;
  tenant_id: string;
  signal: string;
  decision: string;
  entity_id: string | null;
  user_id: string | null;
  trace_id: string | null;
  callback_url: string;
  status: string;
  http_status: number | null;
  attempt_count: number;
  latency_ms: number | null;
  payload_preview: string;
  last_error: string | null;
  created_at: string | null;
  delivered_at: string | null;
};

export type MarketplaceWebhookLogDetail = MarketplaceWebhookLogItem & {
  payload?: Record<string, unknown>;
  attempts?: Array<{
    attempt: number;
    status_code: number | null;
    error: string | null;
    latency_ms: number | null;
    timestamp: string;
  }>;
};

export type MarketplaceWebhookLogsResponse = {
  tenant_id: string;
  items: MarketplaceWebhookLogItem[];
  count: number;
  summary: { delivered: number; failed: number; pending: number };
};

export type AutomatedBackupIndicatorsResponse = {
  updated_at: string;
  backup_dir: string;
  thresholds_hours: { ok: number; warn: number };
  stores: BackupStoreIndicator[];
  schedule_hints?: { postgres: string; janusgraph: string };
};

export type NatsDeadLetterOfficeResponse = {
  stream_name: string;
  dlq_subject: string;
  subject_prefix: string;
  nats_connected: boolean;
  jetstream_enabled: boolean;
  pending_estimate: number | null;
  items: NatsDeadLetterItem[];
  peeked_at: string;
  source?: string;
  error?: string;
};

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
  natsSetuMonitor(tenantId: string) {
    const q = new URLSearchParams({ tenant_id: tenantId });
    return request<NatsSetuMonitorResponse>(`/api/ingress/v1/osint/nats-setu-monitor?${q}`);
  },
};

/** `GET /v1/integrations/scorecards` — per-provider connectivity + connector quality (integration-ingress). */
export interface IntegrationProviderScorecard {
  provider_id: string;
  category: string;
  status: string;
  connectivity_score: number;
  latency_ms: number;
  config_completeness: number;
  last_checked_at: string | null;
  reasons: string[];
  provider_score: number;
  connector_quality: Record<string, unknown>;
}

export interface IntegrationScorecardsPayload {
  tenant_id: string;
  connector_quality_version?: string;
  overall_score: number;
  overall_connector_quality: number;
  providers: IntegrationProviderScorecard[];
}

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

/** ``GET/PUT /v1/compliance/residency/matrix`` — integration-ingress ``compliance_residency.py``. */
export type ResidencyMatrixTenantRow = {
  id: string;
  label?: string;
  residency_region: string;
};

export type ResidencyMatrixVendorColumn = {
  key: string;
  label?: string;
  processing_region: string;
  source?: string;
};

export type ResidencyMatrixResponse = {
  tenants: ResidencyMatrixTenantRow[];
  vendors: ResidencyMatrixVendorColumn[];
  cells: Record<string, boolean>;
  ok?: boolean;
  legend?: { toggle_on: string; toggle_off: string };
};

export type ResidencyMatrixPutBody = {
  tenant_id: string;
  vendor_key: string;
  blocked: boolean;
};

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
    const c = config ?? {};
    if (Object.keys(c).length > 0) {
      assertIntegrationSecretsTransportSecure();
    }
    return request<{ ok: boolean; integration: Record<string, unknown> }>("/api/ingress/v1/integrations/install", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, provider_id: providerId, config: c }),
    });
  },
  uninstall(tenantId: string, providerId: string) {
    return request<{ ok: boolean }>("/api/ingress/v1/integrations/uninstall", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, provider_id: providerId }),
    });
  },
  testConnectivity(tenantId: string, providerId: string, config?: Record<string, unknown>) {
    if (config && Object.keys(config).length > 0) {
      assertIntegrationSecretsTransportSecure();
    }
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
    assertIntegrationSecretsTransportSecure();
    return request<{
      tenant_id: string;
      provider_id: string;
      required_config_fields: string[];
      masked_config: Record<string, string>;
    }>(`/api/ingress/v1/integrations/config/${providerId}?tenant_id=${tenantId}`);
  },
  configure(tenantId: string, providerId: string, config: Record<string, unknown>) {
    assertIntegrationSecretsTransportSecure();
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
  scorecards(tenantId: string) {
    return request<IntegrationScorecardsPayload>(
      `/api/ingress/v1/integrations/scorecards?tenant_id=${encodeURIComponent(tenantId)}`,
    );
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

  systemHealthHud() {
    return request<SystemHealthHudResponse>("/api/ingress/v1/ops/system-health-hud");
  },

  systemBenchmarking(sampleRounds?: number) {
    const q = sampleRounds != null ? `?sample_rounds=${sampleRounds}` : "";
    return request<SystemBenchmarkingResponse>(`/api/ingress/v1/ops/system-benchmarking${q}`);
  },

  failoverToggles() {
    return request<FailoverTogglesState>("/api/ingress/v1/ops/failover-toggles");
  },

  automatedBackupIndicators() {
    return request<AutomatedBackupIndicatorsResponse>("/api/ingress/v1/ops/automated-backup-indicators");
  },

  marketplaceSdkApiKeysCatalog() {
    return request<MarketplaceSdkApiKeysCatalogResponse>("/api/ingress/v1/marketplace/sdk-api-keys/catalog");
  },

  marketplaceSdkApiKeysList(tenantId: string) {
    return request<MarketplaceSdkApiKeysListResponse>(
      `/api/ingress/v1/marketplace/sdk-api-keys?tenant_id=${encodeURIComponent(tenantId)}`,
    );
  },

  marketplaceSdkApiKeysCreate(body: {
    tenant_id: string;
    platform: string;
    label?: string;
    scopes?: string[];
  }) {
    return request<MarketplaceSdkApiKeyCreateResponse>("/api/ingress/v1/marketplace/sdk-api-keys", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  marketplaceSdkApiKeysRevoke(keyId: string, tenantId: string) {
    return request<{ ok: boolean; key: MarketplaceSdkApiKeyRecord }>(
      `/api/ingress/v1/marketplace/sdk-api-keys/${encodeURIComponent(keyId)}/revoke?tenant_id=${encodeURIComponent(tenantId)}`,
      { method: "POST" },
    );
  },

  marketplaceRateLimitShields(tenantId: string) {
    return request<MarketplaceRateLimitShieldsResponse>(
      `/api/ingress/v1/marketplace/rate-limit-shields?tenant_id=${encodeURIComponent(tenantId)}`,
    );
  },

  marketplaceRateLimitShieldUpdate(
    keyId: string,
    body: {
      tenant_id: string;
      enabled?: boolean;
      requests_per_minute?: number;
      burst?: number;
    },
  ) {
    return request<{ ok: boolean; shield: MarketplaceRateLimitShieldItem }>(
      `/api/ingress/v1/marketplace/rate-limit-shields/${encodeURIComponent(keyId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  },

  piiFieldReveal(body: {
    tenant_id: string;
    action: "reveal" | "hide";
    field_kind: string;
    field_path: string;
    context_type?: string;
    context_id?: string;
    value_fingerprint: string;
    masked_preview?: string;
  }) {
    return request<{ ok: boolean; event: PiiFieldRevealAuditItem }>(
      "/api/ingress/v1/compliance/pii-field-reveal",
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  piiFieldRevealAudit(tenantId: string, limit = 100) {
    return request<PiiFieldRevealAuditResponse>(
      `/api/ingress/v1/compliance/pii-field-reveal/audit?tenant_id=${encodeURIComponent(tenantId)}&limit=${limit}`,
    );
  },

  marketplaceWebhookLogs(params?: { tenant_id?: string; status?: string; signal?: string; limit?: number }) {
    const q = new URLSearchParams();
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    if (params?.status) q.set("status", params.status);
    if (params?.signal) q.set("signal", params.signal);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<MarketplaceWebhookLogsResponse>(
      `/api/ingress/v1/marketplace/webhook-logs${qs ? `?${qs}` : ""}`,
    );
  },

  marketplaceWebhookLogDetail(logId: string) {
    return request<MarketplaceWebhookLogDetail>(`/api/ingress/v1/marketplace/webhook-logs/${encodeURIComponent(logId)}`);
  },

  marketplaceWebhookLogRetry(logId: string) {
    return request<{ ok: boolean; log: MarketplaceWebhookLogDetail }>(
      `/api/ingress/v1/marketplace/webhook-logs/${encodeURIComponent(logId)}/retry`,
      { method: "POST" },
    );
  },

  natsDeadLetterOffice(params?: { limit?: number; kind?: string; tenant_id?: string }) {
    const q = new URLSearchParams();
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.kind) q.set("kind", params.kind);
    if (params?.tenant_id) q.set("tenant_id", params.tenant_id);
    const qs = q.toString();
    return request<NatsDeadLetterOfficeResponse>(
      `/api/ingress/v1/ops/nats-dead-letter-office${qs ? `?${qs}` : ""}`,
    );
  },

  setFailoverToggles(body: FailoverTogglesPayload) {
    return request<FailoverTogglesState>("/api/ingress/v1/ops/failover-toggles", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },

  residencyMatrix() {
    const h = decisionServiceApiKeyHeaders();
    return request<ResidencyMatrixResponse>("/api/ingress/v1/compliance/residency/matrix", {
      headers: { "Content-Type": "application/json", ...h },
    });
  },

  residencyMatrixPut(body: ResidencyMatrixPutBody) {
    const h = decisionServiceApiKeyHeaders();
    return request<ResidencyMatrixResponse>("/api/ingress/v1/compliance/residency/matrix", {
      method: "PUT",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", ...h },
    });
  },

  residencyAuditList(filters: ResidencyAuditListParams) {
    const h = decisionServiceApiKeyHeaders();
    const q = buildResidencyAuditQuery(filters, { includePagination: true });
    return request<ResidencyAuditListResponse>(`/api/ingress/v1/compliance/residency/audit?${q}`, {
      headers: { "Content-Type": "application/json", ...h },
    });
  },

  /** ``GET /v1/analytics/promo-abuse`` — unique users per coupon code (Prompt 180). */
  promoAbuse(params: { tenant_id: string; coupon_code?: string; window_days?: number }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.coupon_code) q.set("coupon_code", params.coupon_code);
    if (params.window_days != null) q.set("window_days", String(params.window_days));
    return request<PromoAbuseResponse>(`/api/ingress/v1/analytics/promo-abuse?${q}`);
  },

  /** ``GET /v1/investigation/synthetic-identity-detectors`` — IP/browser/email risk flags (Prompt 181). */
  syntheticIdentityDetectors(params: { tenant_id: string; limit?: number; flag_score?: number }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.limit != null) q.set("limit", String(params.limit));
    if (params.flag_score != null) q.set("flag_score", String(params.flag_score));
    return request<SyntheticIdentityDetectorsResponse>(
      `/api/ingress/v1/investigation/synthetic-identity-detectors?${q}`,
    );
  },

  /** ``GET /v1/marketplace/seller-integrity`` — review-to-delivery integrity scores (Prompt 182). */
  sellerIntegrity(params: { tenant_id: string; window_days?: number; limit?: number }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.window_days != null) q.set("window_days", String(params.window_days));
    if (params.limit != null) q.set("limit", String(params.limit));
    return request<SellerIntegrityResponse>(`/api/ingress/v1/marketplace/seller-integrity?${q}`);
  },

  /** ``GET /v1/marketplace/payout-delay`` — JanusGraph mule_score payout holds (Prompt 183). */
  payoutDelay(params: { tenant_id: string; limit?: number }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.limit != null) q.set("limit", String(params.limit));
    return request<PayoutDelayResponse>(`/api/ingress/v1/marketplace/payout-delay?${q}`);
  },

  payoutDelayUpdateConfig(body: {
    tenant_id: string;
    automation_enabled?: boolean;
    mule_score_hold_threshold?: number;
  }) {
    return request<PayoutDelayResponse>("/api/ingress/v1/marketplace/payout-delay/config", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  payoutDelayRelease(params: { tenant_id: string; payout_id: string }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    return request<PayoutDelayReleaseResponse>(
      `/api/ingress/v1/marketplace/payout-delay/${encodeURIComponent(params.payout_id)}/release?${q}`,
      { method: "POST", body: "{}" },
    );
  },

  /** ``GET /v1/investigation/social-engineering-monitor`` — credential burst after listings (Prompt 184). */
  socialEngineeringMonitor(params: {
    tenant_id: string;
    limit?: number;
    only_flagged?: boolean;
  }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.limit != null) q.set("limit", String(params.limit));
    if (params.only_flagged) q.set("only_flagged", "true");
    return request<SocialEngineeringMonitorResponse>(
      `/api/ingress/v1/investigation/social-engineering-monitor?${q}`,
    );
  },

  socialEngineeringUpdateConfig(body: {
    tenant_id: string;
    high_value_listing_usd?: number;
    credential_change_window_minutes?: number;
  }) {
    return request<SocialEngineeringMonitorResponse>(
      "/api/ingress/v1/investigation/social-engineering-monitor/config",
      { method: "PATCH", body: JSON.stringify(body) },
    );
  },

  /** ``GET /v1/analytics/review-rings`` — users who reviewed the same 5 products (Prompt 185). */
  reviewRings(params: { tenant_id: string; min_ring_size?: number; limit?: number }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.min_ring_size != null) q.set("min_ring_size", String(params.min_ring_size));
    if (params.limit != null) q.set("limit", String(params.limit));
    return request<ReviewRingClustersResponse>(`/api/ingress/v1/analytics/review-rings?${q}`);
  },

  /** ``GET /v1/compliance/kyc-handover`` — cases needing additional ID (Prompt 186). */
  kycHandover(params: { tenant_id: string; case_id?: string }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    if (params.case_id) q.set("case_id", params.case_id);
    return request<KycHandoverBoardResponse>(`/api/ingress/v1/compliance/kyc-handover?${q}`);
  },

  kycHandoverSendEmail(body: { tenant_id: string; case_id: string; analyst_note?: string }) {
    return request<KycHandoverSendResponse>(
      `/api/ingress/v1/compliance/kyc-handover/${encodeURIComponent(body.case_id)}/send-id-email`,
      { method: "POST", body: JSON.stringify({ tenant_id: body.tenant_id, analyst_note: body.analyst_note }) },
    );
  },

  /** ``GET /v1/compliance/regional-risk-toggles`` — sub-region attack-wave blacklists (Prompt 187). */
  regionalRiskToggles(params: { tenant_id: string }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    return request<RegionalRiskTogglesResponse>(`/api/ingress/v1/compliance/regional-risk-toggles?${q}`);
  },

  regionalRiskToggle(body: { tenant_id: string; sub_region_id: string; blacklisted: boolean }) {
    return request<RegionalRiskTogglePatchResponse>(
      `/api/ingress/v1/compliance/regional-risk-toggles/${encodeURIComponent(body.sub_region_id)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          tenant_id: body.tenant_id,
          blacklisted: body.blacklisted,
        }),
      },
    );
  },

  /** ``GET /v1/ops/command-center`` — unified analyst cockpit (Prompt 188). */
  commandCenter(params: { tenant_id: string }) {
    const q = new URLSearchParams({ tenant_id: params.tenant_id });
    return request<CommandCenterResponse>(`/api/ingress/v1/ops/command-center?${q}`);
  },
};

/** Query params for ``GET /v1/compliance/residency/audit`` (list + CSV export filters). */
export type ResidencyAuditListParams = {
  page?: number;
  page_size?: number;
  tenant_id?: string;
  tenant_id_prefix?: string;
  vendor_key_contains?: string;
  outcome?: string;
  component?: string;
  created_after?: string;
  created_before?: string;
};

export type ComplianceResidencyAuditRow = {
  id: string;
  tenant_id: string;
  component: string;
  vendor_key: string;
  tenant_region: string;
  vendor_region: string;
  outcome: string;
  detail: string | null;
  request_url_preview: string | null;
  created_at: string | null;
};

export type ResidencyAuditListResponse = {
  items: ComplianceResidencyAuditRow[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

function buildResidencyAuditQuery(filters: ResidencyAuditListParams, opts: { includePagination: boolean }): string {
  const q = new URLSearchParams();
  if (opts.includePagination) {
    q.set("page", String(filters.page ?? 1));
    q.set("page_size", String(filters.page_size ?? 25));
  }
  const set = (k: keyof ResidencyAuditListParams, name: string) => {
    const v = filters[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") q.set(name, String(v).trim());
  };
  set("tenant_id", "tenant_id");
  set("tenant_id_prefix", "tenant_id_prefix");
  set("vendor_key_contains", "vendor_key_contains");
  set("outcome", "outcome");
  set("component", "component");
  set("created_after", "created_after");
  set("created_before", "created_before");
  return q.toString();
}

/**
 * Download CSV from ``GET /v1/compliance/residency/audit/export.csv`` (server-streamed body; not DOM-derived).
 * Uses ``fetch`` + Blob because the response is not JSON.
 */
export async function downloadComplianceResidencyAuditCsv(filters: ResidencyAuditListParams): Promise<void> {
  const q = buildResidencyAuditQuery(filters, { includePagination: false });
  const url = `/api/ingress/v1/compliance/residency/audit/export.csv?${q}`;
  const res = await fetch(url, { headers: { ...decisionServiceApiKeyHeaders() } });
  if (!res.ok && USE_API_MOCKS) {
    const { getMockResponse } = await import("./mockData");
    const mock = getMockResponse(url, { method: "GET" });
    if (typeof mock === "string") {
      triggerBrowserCsvDownload(mock, "compliance_residency_audit.csv");
      reportDataOutcome("mock");
      return;
    }
  }
  if (!res.ok) {
    const text = await res.text();
    reportDataOutcome("offline");
    throw new Error(parseHttpErrorMessage(res.status, res.statusText, text, res.headers));
  }
  const blob = await res.blob();
  reportDataOutcome("live");
  const cd = res.headers.get("content-disposition") ?? "";
  const m = /filename="([^"]+)"/.exec(cd);
  const filename = m?.[1] ?? "compliance_residency_audit.csv";
  triggerBrowserCsvDownload(await blob.text(), filename);
}

function triggerBrowserCsvDownload(csvText: string, filename: string): void {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.rel = "noopener";
  a.click();
  URL.revokeObjectURL(href);
}

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
  /** Signed URL or HTTPS path to the chargeback / representment PDF uploaded for review. */
  evidence_pdf_url?: string | null;
  /** Markdown narrative from Shadow (device/IP/signature + cryptographic event hash). */
  shadow_evidence_report_markdown?: string | null;
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
