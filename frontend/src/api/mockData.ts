import { ACCESS_GROUPS, requiresMakerChecker } from "../config/accessModuleCatalog";
import { deterministicAuditRecentItem } from "../domain/auditExplorerDeterministic";
import {
  rankFeatureImportanceFromAudit,
  type SaarthiFeatureImportanceRequestBody,
} from "../lib/saarthi/featureImportance";
import { buildTransactionSeed } from "../domain/transactionSeed";
import { mapAnalyticsTransactionRow } from "../utils/mapAnalyticsTransactionRow";
import { isSessionNoiseAuditRow } from "../utils/copilotContext";

type AnyObj = Record<string, unknown>;

const nowIso = () => new Date().toISOString();

/** ISO timestamp ``hours`` before now — for SLA / workload mocks. */
const isoHoursAgo = (hours: number) => new Date(Date.now() - hours * 3600000).toISOString();

const mockPayoutDelayConfigByTenant: Record<
  string,
  { automation_enabled: boolean; mule_score_hold_threshold: number }
> = {};
const mockPayoutDelayReleased = new Set<string>();

const mockSocialEngineeringConfigByTenant: Record<
  string,
  { high_value_listing_usd: number; credential_change_window_minutes: number }
> = {};

const mockKycHandoverSent: Record<string, { sent_at: string; message_id: string; subject: string }> = {};

const mockRegionalRiskBlacklist: Record<string, Record<string, boolean>> = {};

const MOCK_REGIONAL_CATALOG = [
  {
    sub_region_id: "in-mh-mumbai",
    country_code: "IN",
    country_name: "India",
    label: "Maharashtra — Mumbai metro",
    attack_wave_score: 78,
    signals: ["credential_stuffing_spike", "mule_cashout_cluster"],
    incidents_24h: 142,
  },
  {
    sub_region_id: "in-ka-bengaluru",
    country_code: "IN",
    country_name: "India",
    label: "Karnataka — Bengaluru tech corridor",
    attack_wave_score: 52,
    signals: ["sim_swap_reports"],
    incidents_24h: 38,
  },
  {
    sub_region_id: "ng-la-lagos",
    country_code: "NG",
    country_name: "Nigeria",
    label: "Lagos — Lekki / Victoria Island",
    attack_wave_score: 88,
    signals: ["romance_scam_ring", "synthetic_identity_burst"],
    incidents_24h: 96,
  },
  {
    sub_region_id: "br-sp-interior",
    country_code: "BR",
    country_name: "Brazil",
    label: "São Paulo — ABC interior",
    attack_wave_score: 71,
    signals: ["pix_mule_velocity"],
    incidents_24h: 67,
  },
  {
    sub_region_id: "us-fl-miami",
    country_code: "US",
    country_name: "United States",
    label: "Florida — Miami-Dade",
    attack_wave_score: 61,
    signals: ["stolen_card_testing"],
    incidents_24h: 54,
  },
  {
    sub_region_id: "ph-ncr-manila",
    country_code: "PH",
    country_name: "Philippines",
    label: "NCR — Metro Manila",
    attack_wave_score: 84,
    signals: ["bpo_fraud_collusion", "account_farming"],
    incidents_24h: 118,
  },
  {
    sub_region_id: "gb-lon-east",
    country_code: "GB",
    country_name: "United Kingdom",
    label: "London — East End corridor",
    attack_wave_score: 48,
    signals: ["low_grade_phishing"],
    incidents_24h: 22,
  },
  {
    sub_region_id: "vn-hcm-district7",
    country_code: "VN",
    country_name: "Vietnam",
    label: "Ho Chi Minh — District 7",
    attack_wave_score: 73,
    signals: ["marketplace_refund_abuse"],
    incidents_24h: 49,
  },
] as const;

function buildMockRegionalRiskBoard(tid: string): AnyObj {
  const tenantToggles = mockRegionalRiskBlacklist[tid] ?? {};
  const tier = (score: number) => (score >= 80 ? "critical" : score >= 65 ? "elevated" : "normal");
  const sub_regions = MOCK_REGIONAL_CATALOG.map((base) => {
    const defaultBl = base.attack_wave_score >= 80;
    const blacklisted = tenantToggles[base.sub_region_id] ?? defaultBl;
    return {
      ...base,
      attack_tier: tier(base.attack_wave_score),
      blacklisted,
      updated_at: blacklisted ? nowIso() : null,
      updated_by: blacklisted ? "analyst" : null,
      policy_effect: blacklisted ? "block_new_onboarding_and_payouts" : "monitor_only",
    };
  }).sort(
    (a, b) =>
      (a.blacklisted === b.blacklisted ? 0 : a.blacklisted ? -1 : 1) ||
      b.attack_wave_score - a.attack_wave_score,
  );
  const byCountry: Record<string, AnyObj[]> = {};
  for (const r of sub_regions) {
    const code = r.country_code as string;
    if (!byCountry[code]) byCountry[code] = [];
    byCountry[code].push(r);
  }
  const country_groups = Object.entries(byCountry)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([code, items]) => ({
      country_code: code,
      country_name: (items[0] as AnyObj).country_name,
      sub_regions: items,
      blacklisted_count: items.filter((i) => (i as AnyObj).blacklisted).length,
    }));
  const blacklisted = sub_regions.filter((r) => r.blacklisted);
  return {
    tenant_id: tid,
    updated_at: nowIso(),
    source: "mock",
    thresholds: { attack_wave_warn: 65, attack_wave_critical: 80 },
    summary: {
      sub_region_count: sub_regions.length,
      blacklisted_count: blacklisted.length,
      elevated_wave_count: sub_regions.filter((r) => r.attack_tier === "elevated").length,
      critical_wave_count: sub_regions.filter((r) => r.attack_tier === "critical").length,
    },
    signals: blacklisted.length
      ? [`${blacklisted.length} sub-region(s) blacklisted for tenant ${tid}`]
      : [],
    sub_regions,
    country_groups,
  };
}

function buildMockSocialEngineeringBoard(
  tid: string,
  limit: number,
  onlyFlagged: boolean,
): AnyObj {
  if (!mockSocialEngineeringConfigByTenant[tid]) {
    mockSocialEngineeringConfigByTenant[tid] = {
      high_value_listing_usd: 5000,
      credential_change_window_minutes: 10,
    };
  }
  const cfg = mockSocialEngineeringConfigByTenant[tid];
  const profiles = [
    { value: 15000, emailMin: 3.2, passMin: 5.8, flagged: true },
    { value: 8900, emailMin: 4.1, passMin: 7.0, flagged: true },
    { value: 6200, emailMin: 2.5, passMin: 8.2, flagged: true },
    { value: 1200, emailMin: 2.0, passMin: 3.0, flagged: false },
    { value: 450, emailMin: 1.0, passMin: 2.0, flagged: false },
  ];
  const all = Array.from({ length: limit }, (_, i) => {
    const p = profiles[i % profiles.length];
    const listingAt = new Date(Date.now() - i * 4 * 3600000).toISOString();
    const flagged =
      p.value >= cfg.high_value_listing_usd &&
      p.emailMin <= cfg.credential_change_window_minutes &&
      p.passMin <= cfg.credential_change_window_minutes;
    const signals = flagged
      ? [
          "email_change_within_window_of_high_value_listing",
          "password_change_within_window_of_high_value_listing",
          "social_engineering_credential_burst",
        ]
      : [];
    return {
      account_id: `acct_se_mock_${String(i).padStart(3, "0")}`,
      user_id: `user_se_${i}`,
      display_name: `Seller account ${i + 1}`,
      listing_id: `listing_${i}`,
      listing_title: ["Luxury watch", "GPU lot", "Designer sofa", "Textbooks", "Bike"][i % 5],
      listing_value_usd: p.value,
      listing_posted_at: listingAt,
      email_changed_at: flagged
        ? new Date(new Date(listingAt).getTime() + p.emailMin * 60000).toISOString()
        : null,
      password_changed_at: flagged
        ? new Date(new Date(listingAt).getTime() + p.passMin * 60000).toISOString()
        : null,
      minutes_listing_to_email_change: flagged ? p.emailMin : null,
      minutes_listing_to_password_change: flagged ? p.passMin : null,
      is_social_engineering_flag: flagged,
      signals,
      risk_score: flagged ? 92 : 35,
    };
  });
  const accounts = onlyFlagged ? all.filter((a) => a.is_social_engineering_flag) : all;
  const flaggedCount = all.filter((a) => a.is_social_engineering_flag).length;
  return {
    tenant_id: tid,
    updated_at: nowIso(),
    source: "mock",
    config: {
      high_value_listing_usd: cfg.high_value_listing_usd,
      credential_change_window_minutes: cfg.credential_change_window_minutes,
      require_email_and_password_change: true,
    },
    summary: {
      scanned_accounts: all.length,
      flagged_accounts: flaggedCount,
      high_value_threshold_usd: cfg.high_value_listing_usd,
      credential_window_minutes: cfg.credential_change_window_minutes,
    },
    signals:
      flaggedCount > 0
        ? [
            `${flaggedCount} account(s) changed email and password within ${cfg.credential_change_window_minutes}m of a high-value listing`,
          ]
        : [],
    accounts: [...accounts].sort(
      (a, b) =>
        (a.is_social_engineering_flag === b.is_social_engineering_flag
          ? 0
          : a.is_social_engineering_flag
            ? -1
            : 1) || b.risk_score - a.risk_score,
    ),
  };
}

function buildMockPayoutDelayBoard(tid: string, limit: number): AnyObj {
  if (!mockPayoutDelayConfigByTenant[tid]) {
    mockPayoutDelayConfigByTenant[tid] = { automation_enabled: true, mule_score_hold_threshold: 72 };
  }
  const cfg = mockPayoutDelayConfigByTenant[tid];
  const payouts = Array.from({ length: limit }, (_, i) => {
    const muleScore = 28 + (i % 11) * 7;
    const payoutId = `payout_mock_${String(i).padStart(3, "0")}`;
    const releaseKey = `${tid}:${payoutId}`;
    const amount = 450 + i * 320;
    if (mockPayoutDelayReleased.has(releaseKey)) {
      return {
        payout_id: payoutId,
        tenant_id: tid,
        entity_id: `ent_mock_${i}`,
        beneficiary_label: `Beneficiary ·••${1000 + i}`,
        amount_usd: amount,
        currency: "USD",
        channel: ["ach", "wire", "instant", "crypto"][i % 4],
        mule_score: muleScore,
        mule_score_source: "janusgraph",
        janusgraph_vertex_id: `v-ent_mock_${i}`,
        status: "released",
        hold_reason: null,
        held_at: null,
        held_by: null,
        created_at: new Date(Date.now() - i * 600000).toISOString(),
        scheduled_release_at: null,
      };
    }
    const held = cfg.automation_enabled && muleScore >= cfg.mule_score_hold_threshold;
    return {
      payout_id: payoutId,
      tenant_id: tid,
      entity_id: `ent_mock_${i}`,
      beneficiary_label: `Beneficiary ·••${1000 + i}`,
      amount_usd: amount,
      currency: "USD",
      channel: ["ach", "wire", "instant", "crypto"][i % 4],
      mule_score: muleScore,
      mule_score_source: "janusgraph",
      janusgraph_vertex_id: `v-ent_mock_${i}`,
      status: held ? "held" : "pending",
      hold_reason: held ? `janusgraph_mule_score_gte_${cfg.mule_score_hold_threshold}` : null,
      held_at: held ? new Date(Date.now() - 180000).toISOString() : null,
      held_by: held ? "payout_delay_automation" : null,
      created_at: new Date(Date.now() - i * 600000).toISOString(),
      scheduled_release_at: held ? new Date(Date.now() + 72 * 3600000).toISOString() : null,
    };
  });
  const held = payouts.filter((p) => p.status === "held");
  return {
    tenant_id: tid,
    updated_at: nowIso(),
    source: "mock",
    config: {
      automation_enabled: cfg.automation_enabled,
      mule_score_hold_threshold: cfg.mule_score_hold_threshold,
      janusgraph_property: "mule_score",
      hold_duration_hours_default: 72,
    },
    summary: {
      pending_count: payouts.filter((p) => p.status === "pending").length,
      held_count: held.length,
      released_count: payouts.filter((p) => p.status === "released").length,
      held_amount_usd: held.reduce((s, p) => s + Number(p.amount_usd), 0),
      automation_active: cfg.automation_enabled,
    },
    events: held.slice(0, 6).map((p, idx) => ({
      event_id: `evt_mock_${idx}`,
      event_type: "automation_hold",
      payout_id: p.payout_id,
      mule_score: p.mule_score,
      threshold: cfg.mule_score_hold_threshold,
      timestamp: p.held_at ?? nowIso(),
      detail: `JanusGraph mule_score=${p.mule_score} ≥ ${cfg.mule_score_hold_threshold}`,
    })),
    payouts: [...payouts].sort((a, b) => {
      const order = (s: string) => (s === "held" ? 0 : s === "pending" ? 1 : 2);
      return order(String(a.status)) - order(String(b.status)) || Number(b.mule_score) - Number(a.mule_score);
    }),
  };
}

/** Rows for ``GET .../analytics/decisions`` — outcome × ``rule_hits`` attribution demos (Prompt 162). */
function buildMockAnalyticsDecisionRows(): AnyObj[] {
  const rustDeny = ["rs_hard_velocity", "rs_geo_anomaly", "rs_device_mismatch", "tarka_core::blocklist_hit"];
  const rustReview = ["rs_velocity_soft", "rs_ato_signals"];
  const jsonRules = ["velocity_guard", "amount_threshold"];
  const rows: AnyObj[] = [];
  for (let i = 0; i < 48; i++) {
    const decision = i % 6 === 0 ? "allow" : i % 4 === 0 ? "review" : "deny";
    let hits: string[] = [];
    if (decision === "deny") {
      hits = [rustDeny[i % rustDeny.length]];
      if (i % 3 !== 0) hits.push(jsonRules[i % jsonRules.length]);
    } else if (decision === "review") {
      hits = [rustReview[i % rustReview.length]];
      if (i % 2 === 0) hits.push(jsonRules[1]);
    } else if (decision === "allow") {
      hits = i % 8 === 0 ? ["velocity_guard"] : [];
    }
    rows.push({
      trace_id: `tr-rp-${i}-${mockRandomAlpha(6)}`,
      entity_id: `ent_rp_${i}`,
      tenant_id: "demo",
      event_type: "payment",
      decision,
      score: decision === "deny" ? 88 : decision === "review" ? 58 : 22,
      tags: [],
      rule_hits: hits,
      created_at: isoHoursAgo(i),
    });
  }
  return rows;
}

/** Alphanumeric suffix for demo IDs — Web Crypto, not Math.random (CodeQL js/insecure-randomness). */
function mockRandomAlpha(length: number): string {
  const g = globalThis.crypto;
  if (!g?.getRandomValues) {
    throw new Error("Web Crypto API required for mock id generation");
  }
  const buf = new Uint8Array(length);
  g.getRandomValues(buf);
  const alphabet = "0123456789abcdefghijklmnopqrstuvwxyz";
  let s = "";
  for (let i = 0; i < length; i++) {
    s += alphabet[buf[i]! % alphabet.length]!;
  }
  return s;
}

/** Simulated poll counts for ``GET .../ml/export/pit-parquet/jobs/{id}`` in dev mocks. */
const pitParquetMockJobPolls = new Map<string, number>();

/** Stateful blocked cells for ``/api/ingress/v1/compliance/residency/matrix`` mocks (``tenant::vendor``). */
const residencyMatrixMockCells: Record<string, boolean> = {};

function mockResidencyMatrixPayload(): AnyObj {
  return {
    tenants: [
      { id: "demo", label: "Demo / sandbox", residency_region: "GLOBAL" },
      { id: "acme-corp", label: "Acme Corp", residency_region: "US" },
      { id: "eu-financials", label: "EU Financials Ltd", residency_region: "EU" },
    ],
    vendors: [
      { key: "shodan", label: "Shodan", processing_region: "US", source: "osint" },
      { key: "rdap", label: "Rdap", processing_region: "GLOBAL", source: "osint" },
      { key: "jira", label: "Jira", processing_region: "US", source: "connector" },
    ],
    cells: { ...residencyMatrixMockCells },
    legend: {
      toggle_on: "Outbound blocked (pre-socket)",
      toggle_off: "Not administratively blocked (automatic residency rules still apply)",
    },
  };
}

let mockCases: AnyObj[] = [
  {
    id: "c1",
    title: "Velocity spike - fraud_frank",
    status: "open",
    priority: "critical",
    entity_id: "fraud_frank",
    tenant_id: "demo",
    trace_id: "tr-1001",
    assigned_team: "fraud-ops",
    case_type: "Velocity / payments",
    labels: ["velocity", "ring"],
    queue_score: 92,
    recommended_action: "manual_review",
    created_at: nowIso(),
    updated_at: nowIso(),
    /** Narrower than live mock subgraph — use Entity Graph time travel slider to compare vs current neighborhood. */
    graph_snapshot: {
      nodes: [
        { id: "fraud_frank", kind: "User", label: "fraud_frank", device_hash: "snap_bot_01" },
        { id: "user_ring_2", kind: "User", label: "user_ring_2", device_hash: "snap_bot_01" },
        { id: "user_ring_3", kind: "User", label: "user_ring_3", device_hash: "snap_bot_01" },
        { id: "ip_event_only", kind: "IP", label: "198.51.100.1" },
      ],
      links: [
        { source: "fraud_frank", target: "ip_event_only", rel: "FROM" },
        { source: "user_ring_2", target: "ip_event_only", rel: "FROM" },
        { source: "user_ring_3", target: "ip_event_only", rel: "FROM" },
      ],
    },
  },
  {
    id: "c2",
    title: "ATO attempt - user_bob",
    status: "resolved",
    priority: "high",
    entity_id: "user_bob",
    tenant_id: "demo",
    trace_id: "tr-1002",
    assigned_team: "ato",
    case_type: "Account takeover",
    labels: ["ato", "vpn"],
    queue_score: 78,
    recommended_action: "step_up_auth",
    created_at: isoHoursAgo(96),
    updated_at: isoHoursAgo(18),
  },
  {
    id: "c-chargeback-gate",
    title: "Chargeback — duplicate auth",
    status: "closed",
    priority: "high",
    entity_id: "ent_chargeback_demo",
    tenant_id: "demo",
    trace_id: "tr-chargeback-gate",
    assigned_team: "disputes",
    case_type: "Dispute / chargeback",
    labels: ["Dispute"],
    queue_score: 81,
    recommended_action: "manual_review",
    created_at: isoHoursAgo(220),
    updated_at: isoHoursAgo(36),
  },
  ...Array.from({ length: 18 }, (_, i) => {
    const createdH = 320 + i * 10;
    const resolveH = 12 + (i % 8) * 5;
    const isResolved = i % 4 === 1 || i % 4 === 3;
    const status = isResolved ? "closed" : "open";
    const case_type =
      i % 5 === 0 ? "Scam / social engineering" : i % 5 === 2 ? "Velocity / payments" : "General";
    return {
      id: `c-review-scam-${i + 1}`,
      title: `Review Scam — cohort ${String(i + 1).padStart(2, "0")}`,
      status,
      priority: "medium",
      entity_id: `entity_scam_${i + 1}`,
      tenant_id: "demo",
      trace_id: `tr-scam-${i + 1}`,
      assigned_team: "fraud-ops",
      case_type,
      labels: ["scam", "review"],
      queue_score: 52 + (i % 7),
      recommended_action: "queue_review",
      created_at: isoHoursAgo(createdH),
      updated_at: isResolved ? isoHoursAgo(Math.max(1, createdH - resolveH)) : nowIso(),
    };
  }),
];
/** Mutable active AST snapshot for Versioned Rule Control mock (Prompt 172). */
let mockRuleEngineActiveVersion = 4;

const MOCK_RULE_AST_VERSIONS: Array<{
  version: number;
  rule_count: number;
  ast_hash: string;
  created_at: string;
  rules_payload: unknown[];
}> = [
  {
    version: 4,
    rule_count: 12,
    ast_hash: "c4f91a2e8b0d17e3",
    created_at: "2026-05-17T14:22:00.000Z",
    rules_payload: [
      {
        id: "rule-velocity-v4",
        name: "velocity_5m_burst",
        action: "BLOCK",
        priority: 5,
        root_node: { field: { field: "velocity_5m" }, operator: "GT", value: 8 },
      },
    ],
  },
  {
    version: 3,
    rule_count: 11,
    ast_hash: "9e2ac70155f4aa10",
    created_at: "2026-05-16T09:10:00.000Z",
    rules_payload: [
      {
        id: "rule-graph-v3",
        name: "graph_score_elevated",
        action: "SHADOW_REVIEW",
        priority: 8,
        root_node: { field: { field: "graph_score" }, operator: "GT", value: 0.72 },
      },
    ],
  },
  {
    version: 2,
    rule_count: 9,
    ast_hash: "1b77dfe04c3298ac",
    created_at: "2026-05-14T18:45:00.000Z",
    rules_payload: [
      {
        id: "rule-amount-v2",
        name: "high_amount_block",
        action: "BLOCK",
        priority: 5,
        root_node: { field: { field: "amount" }, operator: "GT", value: 5000 },
      },
    ],
  },
  {
    version: 1,
    rule_count: 7,
    ast_hash: "0a9c31e55d2f8811",
    created_at: "2026-05-10T11:00:00.000Z",
    rules_payload: [
      {
        id: "rule-demo-v1",
        name: "demo_shadow_lane",
        action: "SHADOW_REVIEW",
        priority: 10,
        root_node: { field: { field: "amount" }, operator: "GT", value: 200 },
      },
    ],
  },
];

let mockFailoverToggles = {
  graph_plane_disabled: false,
  ai_plane_disabled: false,
  updated_by: null as string | null,
};

const MOCK_SDK_PLATFORMS = [
  {
    id: "sdk-python",
    name: "Python SDK",
    codename: "Duta",
    description: "Server-side evaluate + ingest",
    default_scopes: ["evaluate", "ingest"],
    env_var: "TARKA_API_KEY",
  },
  {
    id: "sdk-typescript",
    name: "TypeScript SDK",
    codename: "Darpana",
    description: "Browser behavioral biometrics + attestation",
    default_scopes: ["evaluate", "ingest", "attestation"],
    env_var: "TARKA_API_KEY",
  },
  {
    id: "sdk-android",
    name: "Android SDK",
    codename: "Kavacha",
    description: "Play Integrity + device signals",
    default_scopes: ["evaluate", "ingest", "attestation"],
    env_var: "TARKA_API_KEY",
  },
  {
    id: "sdk-ios",
    name: "iOS SDK",
    codename: "Mudra",
    description: "App Attest + device signals",
    default_scopes: ["evaluate", "ingest", "attestation"],
    env_var: "TARKA_API_KEY",
  },
  {
    id: "sdk-web",
    name: "Web SDK",
    codename: "Anumana",
    description: "Marketplace web telemetry + ingest",
    default_scopes: ["evaluate", "ingest", "marketplace_profile"],
    env_var: "TARKA_API_KEY",
  },
];

let mockMarketplaceWebhookLogs: Array<{
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
  created_at: string;
  delivered_at: string | null;
}> = [
  {
    id: "wh-demo-1",
    tenant_id: "demo",
    signal: "block",
    decision: "BLOCK",
    entity_id: "ent_mkt_8821",
    user_id: "usr_4412",
    trace_id: "tr-9f2a11",
    callback_url: "https://marketplace-client.example/hooks/fraud-block",
    status: "delivered",
    http_status: 200,
    attempt_count: 1,
    latency_ms: 38,
    payload_preview: '{"signal":"block","decision":"BLOCK"}',
    last_error: null,
    created_at: "2026-05-17T16:02:00.000Z",
    delivered_at: "2026-05-17T16:02:00.042Z",
  },
  {
    id: "wh-demo-2",
    tenant_id: "demo",
    signal: "block",
    decision: "BLOCK",
    entity_id: "ent_mkt_9901",
    user_id: "usr_2290",
    trace_id: "tr-7c88de",
    callback_url: "https://partner-api.example/v1/risk/signals",
    status: "failed",
    http_status: 503,
    attempt_count: 3,
    latency_ms: 1204,
    payload_preview: '{"signal":"block","decision":"BLOCK"}',
    last_error: "HTTP 503",
    created_at: "2026-05-17T15:48:00.000Z",
    delivered_at: null,
  },
  {
    id: "wh-demo-3",
    tenant_id: "demo",
    signal: "block",
    decision: "BLOCK",
    entity_id: "ent_ring_12",
    user_id: "usr_ring_12",
    trace_id: "tr-coord-01",
    callback_url: "https://marketplace-client.example/hooks/fraud-block",
    status: "pending",
    http_status: null,
    attempt_count: 0,
    latency_ms: null,
    payload_preview: '{"signal":"block","decision":"BLOCK"}',
    last_error: null,
    created_at: "2026-05-17T16:10:00.000Z",
    delivered_at: null,
  },
];

let mockMarketplaceSdkKeys: Array<{
  id: string;
  tenant_id: string;
  platform: string;
  label: string;
  key_prefix: string;
  scopes: string[];
  status: string;
  created_at: string;
  last_used_at: string | null;
  created_by: string | null;
  rate_limit_enabled?: boolean;
  rate_limit_rpm?: number;
  rate_limit_burst?: number;
}> = [
  {
    id: "msk-demo-1",
    tenant_id: "demo",
    platform: "sdk-typescript",
    label: "Demo web checkout",
    key_prefix: "tarka_mkt_ab12…9xyz",
    scopes: ["evaluate", "ingest", "attestation"],
    status: "active",
    created_at: "2026-05-10T11:00:00.000Z",
    last_used_at: "2026-05-17T08:22:00.000Z",
    created_by: "analyst-mock",
    rate_limit_enabled: true,
    rate_limit_rpm: 600,
    rate_limit_burst: 50,
  },
  {
    id: "msk-demo-2",
    tenant_id: "demo",
    platform: "sdk-android",
    label: "Staging mobile",
    key_prefix: "tarka_mkt_cd34…1abc",
    scopes: ["evaluate", "ingest", "attestation"],
    status: "active",
    created_at: "2026-05-12T09:00:00.000Z",
    last_used_at: null,
    created_by: "analyst-mock",
    rate_limit_enabled: true,
    rate_limit_rpm: 120,
    rate_limit_burst: 20,
  },
];

const mockRateLimitLive: Record<
  string,
  { requests_in_window: number; remaining: number; throttled: boolean; rejected_total: number }
> = {
  "msk-demo-1": { requests_in_window: 38, remaining: 12, throttled: false, rejected_total: 2 },
  "msk-demo-2": { requests_in_window: 20, remaining: 0, throttled: true, rejected_total: 14 },
};

let mockPiiRevealAudit: Array<{
  id: string;
  tenant_id: string;
  actor_id: string | null;
  action: string;
  field_kind: string;
  field_path: string;
  context_type: string;
  context_id: string | null;
  value_fingerprint: string;
  masked_preview: string;
  created_at: string;
}> = [];

function mockShieldItemFromKey(k: (typeof mockMarketplaceSdkKeys)[number]) {
  const rpm = k.rate_limit_rpm ?? 600;
  const burst = k.rate_limit_burst ?? 50;
  const live = mockRateLimitLive[k.id] ?? {
    requests_in_window: 0,
    remaining: burst,
    throttled: false,
    rejected_total: 0,
  };
  return {
    key_id: k.id,
    tenant_id: k.tenant_id,
    platform: k.platform,
    label: k.label,
    key_prefix: k.key_prefix,
    status: k.status,
    shield: {
      enabled: k.rate_limit_enabled !== false,
      requests_per_minute: rpm,
      burst,
    },
    live: {
      ...live,
      throttled_until: live.throttled ? new Date(Date.now() + 45_000).toISOString() : null,
    },
  };
}

let mockDisputes: AnyObj[] = [
  {
    id: "d1",
    case_id: "c1",
    tenant_id: "demo",
    entity_id: "fraud_frank",
    trace_id: "tr-1001",
    dispute_type: "chargeback",
    status: "open",
    reason_code: "fraudulent",
    amount: 1499.99,
    currency: "USD",
    merchant_id: "CryptoExchange",
    card_network: "visa",
    original_decision: "deny",
    original_score: 92,
    original_rule_hits: ["velocity"],
    original_ml_score: 0.86,
    outcome: null,
    resolution_notes: null,
    filed_at: nowIso(),
    resolved_at: null,
    created_at: nowIso(),
    updated_at: nowIso(),
    evidence_pdf_url: "https://www.w3.org/WAI/WCAG21/working-examples/pdf-note/note.pdf",
    shadow_evidence_report_markdown:
      "## Shadow AI evidence report (sample)\n\n" +
      "- **Ingress IP:** `198.51.100.77`\n" +
      "- **Device hash:** `deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef`\n" +
      "- **Authorization:** 3DS2 frictionless + e-sign `ESIGN-127-GATE`\n\n" +
      "### Cryptographic event anchor\n\n" +
      "SHA-256 event digest (hex): `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbcccccccccccccccccccccccccccccccc`\n",
  },
];
let mockListEntries: AnyObj[] = [
  { list_type: "blocklist", tenant_id: "demo", entity_id: "fraud_frank", reason: "Known fraud ring", created_by: "seed", expires_at: null, metadata: {}, created_at: nowIso() },
  { list_type: "watchlist", tenant_id: "demo", entity_id: "mule_ivan", reason: "Mule behavior", created_by: "seed", expires_at: null, metadata: {}, created_at: nowIso() },
];
const mockInstalledIntegrations: AnyObj[] = [
  { provider_id: "sift", status: "active", category: "device_intelligence" },
  { provider_id: "ip_quality_score", status: "active", category: "ip_intelligence" },
  { provider_id: "jira", status: "active", category: "crm" },
];

/** Pending / approved integration requests (GitHub ticket only after admin approve). */
const mockIntegrationRequests: AnyObj[] = [];

const mockAdminUsers: AnyObj[] = [
  {
    user_id: "u-alex",
    name: "Alex Chen",
    email: "alex.chen@demo.tarka",
    role: "risk_analyst",
    access_policy_id: "risk_analyst",
    can_manage_access: false,
    allowed_modules: [
      "dashboard",
      "cases",
      "disputes",
      "graph",
      "investigation",
      "osint",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "compliance",
      "notifications",
      "settings",
    ],
    last_login: nowIso(),
  },
  {
    user_id: "u-jordan",
    name: "Jordan Lee",
    email: "jordan.lee@demo.tarka",
    role: "engineering",
    access_policy_id: "engineering",
    can_manage_access: false,
    allowed_modules: [
      "dashboard",
      "cases",
      "disputes",
      "graph",
      "investigation",
      "osint",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "compliance",
      "integrations",
      "notifications",
      "settings",
    ],
    last_login: nowIso(),
  },
  {
    user_id: "u-dana",
    name: "Dana Ng",
    email: "dana.ng@demo.tarka",
    role: "data_scientist",
    access_policy_id: "data_science",
    can_manage_access: false,
    allowed_modules: [
      "dashboard",
      "cases",
      "disputes",
      "investigation",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "notifications",
      "settings",
    ],
    last_login: nowIso(),
  },
  {
    user_id: "u-sam",
    name: "Sam Rivera",
    email: "sam.rivera@demo.tarka",
    role: "viewer",
    access_policy_id: "view_only",
    can_manage_access: false,
    allowed_modules: ["dashboard", "notifications", "settings"],
    last_login: nowIso(),
  },
  {
    user_id: "u-rik",
    name: "Rik Okonkwo",
    email: "rik.okonkwo@demo.tarka",
    role: "governance_lead",
    access_policy_id: "governance",
    can_manage_access: true,
    allowed_modules: [
      "dashboard",
      "cases",
      "disputes",
      "analytics",
      "compliance",
      "integrations",
      "notifications",
      "settings",
      "admin",
    ],
    last_login: nowIso(),
  },
  {
    user_id: "u-morgan",
    name: "Morgan Patel",
    email: "morgan.patel@demo.tarka",
    role: "platform_admin",
    access_policy_id: "platform_admin",
    can_manage_access: true,
    allowed_modules: [
      "dashboard",
      "cases",
      "disputes",
      "graph",
      "investigation",
      "osint",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "compliance",
      "integrations",
      "notifications",
      "settings",
      "admin",
    ],
    last_login: nowIso(),
  },
];

const mockAdminSessions: AnyObj[] = [
  {
    session_id: "sess-alex-1",
    user_id: "u-alex",
    user_name: "Alex Chen",
    email: "alex.chen@demo.tarka",
    current_route: "/cases/c1",
    last_activity: nowIso(),
    ip: "203.0.113.44",
    clicks_last_5m: 42,
    entities_touched_1h: 18,
    case_actions_1h: 9,
    avg_dwell_seconds: 12,
  },
  {
    session_id: "sess-jordan-1",
    user_id: "u-jordan",
    user_name: "Jordan Lee",
    email: "jordan.lee@demo.tarka",
    current_route: "/rules",
    last_activity: nowIso(),
    ip: "198.51.100.10",
    clicks_last_5m: 14,
    entities_touched_1h: 3,
    case_actions_1h: 2,
    avg_dwell_seconds: 95,
  },
  {
    session_id: "sess-sam-1",
    user_id: "u-sam",
    user_name: "Sam Rivera",
    email: "sam.rivera@demo.tarka",
    current_route: "/dashboard",
    last_activity: nowIso(),
    ip: "192.0.2.55",
    clicks_last_5m: 6,
    entities_touched_1h: 1,
    case_actions_1h: 0,
    avg_dwell_seconds: 210,
  },
  {
    session_id: "sess-morgan-1",
    user_id: "u-morgan",
    user_name: "Morgan Patel",
    email: "morgan.patel@demo.tarka",
    current_route: "/admin",
    last_activity: new Date(Date.now() - 60_000).toISOString(),
    ip: "198.51.100.88",
    clicks_last_5m: 22,
    entities_touched_1h: 0,
    case_actions_1h: 0,
    avg_dwell_seconds: 180,
  },
  {
    session_id: "sess-alex-2",
    user_id: "u-alex",
    user_name: "Alex Chen",
    email: "alex.chen@demo.tarka",
    current_route: "/investigation",
    last_activity: new Date(Date.now() - 90_000).toISOString(),
    ip: "203.0.113.44",
    clicks_last_5m: 31,
    entities_touched_1h: 6,
    case_actions_1h: 1,
    avg_dwell_seconds: 44,
  },
];

const mockPlatformAudit: AnyObj[] = [
  {
    id: "ae-1",
    ts: new Date(Date.now() - 120_000).toISOString(),
    user_id: "u-alex",
    user_name: "Alex Chen",
    action: "view",
    resource: "cases:detail:c1",
    detail: "Opened case timeline",
    ip: "203.0.113.44",
    flags: [{ type: "high_click_rate", severity: "warning", note: "112 actions / 5m vs baseline 25" }],
  },
  {
    id: "ae-2",
    ts: new Date(Date.now() - 300_000).toISOString(),
    user_id: "u-jordan",
    user_name: "Jordan Lee",
    action: "change",
    resource: "rules:pack:velocity_guard",
    detail: "Drafted score delta +8 → +15",
    ip: "198.51.100.10",
    flags: [{ type: "high_risk_rule_change", severity: "critical", note: "Tier-1 velocity rule" }],
  },
  {
    id: "ae-3",
    ts: new Date(Date.now() - 400_000).toISOString(),
    user_id: "u-alex",
    user_name: "Alex Chen",
    action: "query",
    resource: "graph:subgraph",
    detail: "Expanded 2-hop neighborhood",
    ip: "203.0.113.44",
    flags: [{ type: "high_entity_access", severity: "warning", note: "47 distinct entities in 20m" }],
  },
  {
    id: "ae-4",
    ts: new Date(Date.now() - 600_000).toISOString(),
    user_id: "u-sam",
    user_name: "Sam Rivera",
    action: "view",
    resource: "cases:list",
    detail: "Filtered open + critical",
    ip: "192.0.2.55",
    flags: [],
  },
  {
    id: "ae-5",
    ts: new Date(Date.now() - 720_000).toISOString(),
    user_id: "u-alex",
    user_name: "Alex Chen",
    action: "change",
    resource: "cases:status:c2",
    detail: "open → resolved in 38s",
    ip: "203.0.113.44",
    flags: [{ type: "low_aht_anomaly", severity: "warning", note: "Faster than p05 for similar priority" }],
  },
  {
    id: "ae-6",
    ts: new Date(Date.now() - 900_000).toISOString(),
    user_id: "u-unknown",
    user_name: "API service account",
    action: "query",
    resource: "ingress:opa_bypass_probe",
    detail: "Rejected malformed policy path",
    ip: "10.0.0.12",
    flags: [{ type: "guardrail_bypass_attempt", severity: "critical", note: "Hardening blocked unauthorized OPA admin path" }],
  },
  {
    id: "ae-7",
    ts: new Date(Date.now() - 1_000_000).toISOString(),
    user_id: "u-jordan",
    user_name: "Jordan Lee",
    action: "change",
    resource: "integrations:vault:kms",
    detail: "Rotation job scheduled",
    ip: "198.51.100.10",
    flags: [{ type: "core_config_change", severity: "high", note: "KMS / vault plane" }],
  },
  {
    id: "ae-8",
    ts: new Date(Date.now() - 1_100_000).toISOString(),
    user_id: "u-morgan",
    user_name: "Morgan Patel",
    action: "view",
    resource: "admin:panel:overview",
    detail: "Opened Admin Panel — overview tab",
    ip: "198.51.100.88",
    flags: [],
  },
  {
    id: "ae-9",
    ts: new Date(Date.now() - 1_150_000).toISOString(),
    user_id: "u-alex",
    user_name: "Alex Chen",
    action: "query",
    resource: "investigation:copilot:chat",
    detail: "Investigation Copilot — batch analysis skill (mock)",
    ip: "203.0.113.44",
    flags: [],
  },
  {
    id: "ae-10",
    ts: new Date(Date.now() - 1_200_000).toISOString(),
    user_id: "u-jordan",
    user_name: "Jordan Lee",
    action: "view",
    resource: "admin:audit:export",
    detail: "Exported flagged audit slice (CSV) — demo",
    ip: "198.51.100.10",
    flags: [{ type: "core_config_change", severity: "info", note: "Bulk export of security events" }],
  },
];

const mockAdminApprovals: AnyObj[] = [
  {
    id: "ap-pending-1",
    status: "pending",
    requested_at: new Date(Date.now() - 3_600_000).toISOString(),
    requested_by: "u-jordan",
    requested_by_name: "Jordan Lee",
    summary: "Change affects core module: Admin Panel",
    risk_tier: "core",
    required_approvals: 2,
    target_user_id: "u-sam",
    target_user_name: "Sam Rivera",
    proposed_allowed_modules: [
      "dashboard",
      "analytics",
      "notifications",
      "settings",
      "admin",
    ],
    previous_allowed_modules: ["dashboard", "analytics", "notifications", "settings"],
    votes: [{ user_id: "u-jordan", user_name: "Jordan Lee", at: new Date(Date.now() - 3_500_000).toISOString() }],
  },
  {
    id: "ap-pending-2",
    status: "pending",
    requested_at: new Date(Date.now() - 1_800_000).toISOString(),
    requested_by: "u-alex",
    requested_by_name: "Alex Chen",
    summary: "Change affects high-risk module(s): Rules, Simulation",
    risk_tier: "high",
    required_approvals: 2,
    target_user_id: "u-alex",
    target_user_name: "Alex Chen",
    proposed_allowed_modules: [
      "dashboard",
      "cases",
      "disputes",
      "graph",
      "investigation",
      "notifications",
      "settings",
      "rules",
      "simulation",
    ],
    previous_allowed_modules: ["dashboard", "cases", "disputes", "graph", "investigation", "notifications", "settings"],
    votes: [],
  },
  {
    id: "ap-approved-1",
    status: "approved",
    requested_at: new Date(Date.now() - 86_400_000).toISOString(),
    requested_by: "u-morgan",
    requested_by_name: "Morgan Patel",
    summary: "Change affects high-risk module(s): OSINT",
    risk_tier: "high",
    required_approvals: 2,
    target_user_id: "u-sam",
    target_user_name: "Sam Rivera",
    proposed_allowed_modules: ["dashboard", "analytics", "notifications", "settings", "osint"],
    previous_allowed_modules: ["dashboard", "analytics", "notifications", "settings"],
    votes: [
      { user_id: "u-jordan", user_name: "Jordan Lee", at: new Date(Date.now() - 85_000_000).toISOString() },
      { user_id: "u-morgan", user_name: "Morgan Patel", at: new Date(Date.now() - 84_500_000).toISOString() },
    ],
  },
];

function id(prefix: string) {
  return `${prefix}-${mockRandomAlpha(6)}`;
}

function parsePath(url: string) {
  return url.split("?")[0];
}

/** Narrative + follow-ups from platform audit rows (Admin security feed). */
function buildAuditAnalysisParagraph(events: AnyObj[]): string {
  const lines: string[] = [
    "**Platform audit context** — recent user actions from the security/audit feed (see tool `get_platform_audit_feed`).",
  ];
  const critical = events.filter((e) =>
    (e.flags as AnyObj[] | undefined)?.some((f) => f.severity === "critical"),
  );
  const warning = events.filter((e) =>
    (e.flags as AnyObj[] | undefined)?.some((f) => f.severity === "warning"),
  );
  lines.push("**Suggested follow-ups from this activity:**");
  if (critical.length) {
    const res = critical
      .map((c) => String(c.resource ?? ""))
      .filter(Boolean)
      .slice(0, 3)
      .join(", ");
    lines.push(
      `- **Critical-flagged events (${critical.length}):** escalate to governance/security; do not promote rule changes until \`${res || "listed resources"}\` is reviewed.`,
    );
  }
  if (warning.length) {
    lines.push(
      `- **Warning-flagged events (${warning.length}):** consider session review, breaks for analysts with extreme click volume, or AHT coaching where “too fast” closures appear.`,
    );
  }
  const ruleEdits = events.filter((e) => String(e.resource ?? "").includes("rules:pack"));
  if (ruleEdits.length) {
    lines.push(
      `- **Rule-pack activity detected:** run a **peer review** and capture pack version before/after; schedule replay on a fixed trace slice.`,
    );
  }
  if (!critical.length && !warning.length && !ruleEdits.length) {
    lines.push("- No flags in this audit slice; keep normal triage and verify case facts with tools.");
  }
  return lines.join("\n");
}

/** Mirror investigation-agent + UI filtering for demo responses. */
function applyInvestigationMockContextOptions(body: AnyObj, events: AnyObj[]): AnyObj[] {
  const co = body.context_options as Record<string, unknown> | undefined;
  if (co && co.track_historical_actions === false) {
    return [];
  }
  let out = [...events];
  if (co?.only_session && co.session_started_at) {
    const start = Date.parse(String(co.session_started_at));
    if (!Number.isNaN(start)) {
      out = out.filter((e) => {
        const t = Date.parse(String(e.ts ?? ""));
        return !Number.isNaN(t) && t >= start;
      });
    }
  }
  if (co?.skip_session_actions) {
    out = out.filter(
      (e) =>
        !isSessionNoiseAuditRow({
          resource: String(e.resource ?? ""),
          detail: String(e.detail ?? ""),
        }),
    );
  }
  return out;
}

function mockInvestigationClaims(toolCallsLen: number): { text: string; source: "tool" | "unknown" }[] {
  const claims: { text: string; source: "tool" | "unknown" }[] = [
    { text: "Offline demo mock: connect investigation-agent for live tool-backed claims.", source: "unknown" },
  ];
  if (toolCallsLen > 0) {
    claims.push({
      text: "Simulated tool steps above are for UI demo only, not production Case/Graph APIs.",
      source: "unknown",
    });
  }
  return claims;
}

/** Aligns demo tool rows with live `source_refs` cards (tool, ok, key ids). */
function buildMockSourceReferenceCards(toolCalls: AnyObj[]): AnyObj[] {
  return toolCalls.map((tc) => {
    const name = String(tc.tool ?? tc.name ?? "");
    let args: Record<string, unknown> = {};
    try {
      const raw =
        typeof tc.arguments === "string"
          ? tc.arguments
          : tc.args != null
            ? JSON.stringify(tc.args)
            : "{}";
      args = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      args = {};
    }
    let result: AnyObj = {};
    try {
      const r = tc.result;
      if (typeof r === "string") {
        result = JSON.parse(r) as AnyObj;
      } else if (r && typeof r === "object") {
        result = r as AnyObj;
      }
    } catch {
      result = {};
    }
    const ok = result.error == null;
    const card: AnyObj = { tool: name, ok };
    for (const key of ["case_id", "entity_id", "trace_id", "batch_id"]) {
      const v = args[key];
      if (v != null && String(v).trim()) {
        card[key] = String(v).trim();
      }
    }
    if (result.error != null) {
      card.error = String(result.error).slice(0, 120);
    }
    return card;
  });
}

function finalizeInvestigationMockReply(
  reply: string,
  tool_calls: AnyObj[],
  body: AnyObj,
  opts: { includeAudit?: boolean } = {},
): AnyObj {
  const pbRaw = body.playbook_id;
  const playbookEcho =
    typeof pbRaw === "string" && pbRaw.trim() ? (pbRaw.trim() as string) : undefined;

  const finish = (
    r: string,
    tools: AnyObj[],
    claims: { text: string; source: "tool" | "unknown" }[],
  ) => {
    const turnId = `mock-${Date.now()}-${mockRandomAlpha(7)}`;
    const det = claims.map((c, i) => ({
      claim_index: i,
      supported: c.source === "unknown" ? true : false,
      method: "mock_demo",
      hint: null as string[] | null,
    }));
    return {
      reply: r,
      tool_calls: tools,
      claims,
      source_refs: buildMockSourceReferenceCards(tools),
      turn_id: turnId,
      prompt_version: "3.2.0-mock",
      answer_sections: {
        sections_found: ["facts_from_tools", "inferences", "unknowns", "next_steps"],
        facts_from_tools: "(Demo) See tool_calls and narrative.",
        inferences: "(Demo) Hypotheses not verified against live APIs.",
        unknowns: "None in mock.",
        next_steps: "Connect investigation-agent for full structured output.",
      },
      claims_deterministic_support: det,
      evidence_bundle_draft: {
        schema_hint: "tarka.evidence_bundle_draft/v0",
        turn_id: turnId,
        prompt_version: "3.2.0-mock",
        tool_invocation_count: tools.length,
      },
      ...(playbookEcho ? { playbook_id: playbookEcho } : {}),
    };
  };

  if (opts.includeAudit === false) {
    return finish(reply, tool_calls, mockInvestigationClaims(tool_calls.length));
  }
  const co = body.context_options as Record<string, unknown> | undefined;
  if (co && co.track_historical_actions === false) {
    return finish(reply, tool_calls, mockInvestigationClaims(tool_calls.length));
  }
  const fromBody = body.platform_audit as AnyObj[] | undefined;
  let rawAudit =
    Array.isArray(fromBody) && fromBody.length > 0
      ? [...fromBody].sort((a, b) => String(b.ts).localeCompare(String(a.ts))).slice(0, 30)
      : [...mockPlatformAudit].sort((a, b) => String(b.ts).localeCompare(String(a.ts))).slice(0, 20);

  rawAudit = applyInvestigationMockContextOptions(body, rawAudit).slice(0, 30);
  if (rawAudit.length === 0) {
    return finish(reply, tool_calls, mockInvestigationClaims(tool_calls.length));
  }

  const toolAuditFeed = {
    tool: "get_platform_audit_feed",
    name: "get_platform_audit_feed",
    arguments: JSON.stringify({
      source: fromBody?.length ? "client_platform_audit" : "demo_seed",
      limit: rawAudit.length,
    }),
    result: JSON.stringify({
      count: rawAudit.length,
      events: rawAudit.slice(0, 12).map((e) => ({
        id: e.id,
        ts: e.ts,
        user_name: e.user_name,
        action: e.action,
        resource: e.resource,
        detail: String(e.detail ?? "").slice(0, 100),
        flag_count: Array.isArray(e.flags) ? e.flags.length : 0,
      })),
    }),
  };

  const mergedTools = [...tool_calls, toolAuditFeed];
  return finish(
    `${reply}\n\n${buildAuditAnalysisParagraph(rawAudit)}`,
    mergedTools,
    mockInvestigationClaims(mergedTools.length),
  );
}

/** Rich demo responses for Investigation Copilot when backends are offline. */
function mockInvestigationChatResponse(body: AnyObj): AnyObj {
  const messages = (body.messages as AnyObj[]) ?? [];
  const userMsgs = messages.filter((m) => m.role === "user");
  const last = userMsgs.length ? String(userMsgs[userMsgs.length - 1].content ?? "") : "";
  const t = last.toLowerCase();
  const caseId = body.case_id != null ? String(body.case_id) : "";
  const batchId = body.batch_id != null ? String(body.batch_id) : "";
  const tenantId = String(body.tenant_id ?? "demo");

  const toolCase = {
    tool: "get_case_context",
    name: "get_case_context",
    arguments: JSON.stringify({ case_id: caseId || null, tenant_id: tenantId }),
    result: JSON.stringify({
      case_id: caseId || "c-demo",
      trace_id: "tr-1001",
      priority: "critical",
      labels: ["velocity", "vpn"],
      hint: "Synthetic case context for demo UI",
    }),
  };
  const toolAudit = {
    tool: "get_decision_audit",
    name: "get_decision_audit",
    arguments: JSON.stringify({ trace_id: "tr-1001", tenant_id: tenantId }),
    result: JSON.stringify({
      decision: "review",
      score: 74,
      rule_hits: ["velocity_guard"],
      drivers: ["hostile_or_anonymous_network_path"],
    }),
  };
  const toolGraph = {
    tool: "graph_neighborhood",
    name: "graph_neighborhood",
    arguments: JSON.stringify({ entity_id: "fraud_frank", hops: 2 }),
    result: JSON.stringify({
      nodes: 12,
      edges: 18,
      flagged_neighbors: 3,
      note: "Mock subgraph stats",
    }),
  };

  if (t.includes("/skill")) {
    return finalizeInvestigationMockReply(
      "I see a **/skill**-style message in the chat transcript. The skill catalog is rendered locally in the UI—open the preset list or type `/skill` in the composer for ids. I can still help interpret any skill output once you run it.",
      [],
      body,
      { includeAudit: false },
    );
  }
  if (t.includes("audit") || t.includes("platform log") || t.includes("user actions") || t.includes("who changed")) {
    return finalizeInvestigationMockReply(
      [
        "**Audit-focused answer (mock)** — Cross-check the **platform audit feed** for who changed rules, who hit graph heavily, and any **guardrail** or **critical** flags.",
        "Pair that with **get_decision_audit** for the case trace and **list_cases** for queue pressure so actions are grounded.",
      ].join("\n\n"),
      [toolAudit],
      body,
    );
  }
  if (t.includes("batch") || t.includes("cohort") || t.includes("export")) {
    return finalizeInvestigationMockReply(
      [
        "**Batch / cohort (mock)** — Segment by score decile, channel, and entity age first; watch for selection bias after marketing pushes.",
        "1. Pull decisions + case outcomes for the window; join on `entity_id`.",
        "2. Hypotheses to test: velocity drift, geo concentration, new device ratio vs baseline.",
        "3. Next: run a small labeled review set before changing thresholds.",
        `_Tenant ${tenantId} · case link: ${caseId || "none"}_`,
      ].join("\n\n"),
      [toolCase, toolAudit],
      body,
    );
  }
  if (t.includes("a/b") || t.includes("ab test") || t.includes("shadow") || t.includes("experiment")) {
    return finalizeInvestigationMockReply(
      "**Experiment readout (mock)** — Hold segment mix constant. Primary: review rate & estimated $ at risk; guardrail: deny false-positive proxy. Run at least one full weekly cycle before promote; pre-define rollback if review queue >15% over baseline.",
      [toolAudit],
      body,
    );
  }
  if (t.includes("report") || t.includes("monitoring") || t.includes("weekly") || t.includes("digest")) {
    return finalizeInvestigationMockReply(
      "**Monitoring report skeleton (mock)** — (1) Volume & decision mix (2) SLA / aging (3) Top entities (4) Rule leaders (5) Graph rings called out (6) Experiments (7) Action items. Replace date placeholders before sharing.",
      [],
      body,
    );
  }
  if (t.includes("rule") && (t.includes("gap") || t.includes("improve") || t.includes("opa"))) {
    return finalizeInvestigationMockReply(
      "**Rule-base ideas (mock, advisory)** — Tighten velocity windows for high-risk channels; add list cross-check for devices seen on >3 entities in 24h; tag VPN + emulator combo for manual review. Validate via replay before production.",
      [toolAudit, toolGraph],
      body,
    );
  }
  if (t.includes("tldr") || t.includes("summary") || t.includes("triage")) {
    return finalizeInvestigationMockReply(
      [
        "**TL;DR (mock)**",
        "• Case signals point to scripted/automation + hostile network path.",
        "• Decision: review — velocity_guard fired; ML score elevated.",
        "• Next: expand graph 2-hop, confirm mule links, document for SAR if pattern holds.",
      ].join("\n"),
      [toolCase, toolAudit],
      body,
    );
  }

  const batchHint = batchId
    ? `_Active **batch_id** (\`${batchId.slice(0, 8)}…\`) — live agent would use **get_batch_profile**, **query_batch_rows**, **aggregate_batch_column** on this upload._`
    : "_No batch file attached — use **Upload batch** (CSV / JSON / Excel) for tabular analysis._";

  return finalizeInvestigationMockReply(
    [
      "**Copilot (mock)** — I’m running in **demo mode** without the live investigation agent.",
      "Your message is in context; typical next steps: pull **case + audit**, then **graph neighborhood**, then compare **velocity vs peers**.",
      caseId ? `_Linked case: \`${caseId.slice(0, 12)}…\`_` : "_No case_id in URL — open from a case for tighter context._",
      batchHint,
      "",
      "_Synthetic tool rows below illustrate cross-module pulls (Cases, Decisions, Graph, Platform audit)._",
    ].join("\n"),
    [toolCase, toolGraph],
    body,
  );
}

function safeParseRequestBody(init?: RequestInit): AnyObj {
  if (!init?.body || typeof init.body !== "string") return {};
  try {
    return JSON.parse(init.body) as AnyObj;
  } catch {
    return {};
  }
}

const SAR_FILING_AUTOMATED_ACTOR_IDS = new Set(["sar_worker", "system", "automation", "bot"]);

/**
 * Validates JSON body for ``POST .../sar/intents/{id}/approve`` (human gate before ``FILED``).
 * Exported for unit tests.
 */
export function assertHumanActorIdForSarFiling(body: AnyObj): string {
  const raw = body.actor_id;
  const id = typeof raw === "string" ? raw.trim() : "";
  if (!id || SAR_FILING_AUTOMATED_ACTOR_IDS.has(id)) {
    throw new Error(
      `422 SAR_FILING_REQUIRES_HUMAN_ACTOR: Approve for filing requires a human actor_id in the JSON body (non-empty string; automated actor ids are rejected).`,
    );
  }
  return id;
}

/** Mutable SAR intent rows for `GET /sar/intents` + approve / queue-sftp mocks. */
const mockSarIntentStore: Record<string, AnyObj[]> = {};

function ensureMockSarIntents(caseId: string): AnyObj[] {
  if (!mockSarIntentStore[caseId]) {
    const ts = nowIso();
    const intentId = id("sar-intent");
    mockSarIntentStore[caseId] = [
      {
        id: intentId,
        status: "PENDING_REVIEW",
        sar_artifact_id: id("sar-artifact"),
        created_at: ts,
        updated_at: ts,
        investigative_notes_html: "<p></p>",
        audit_log: [
          {
            id: id("aud"),
            from_status: null,
            to_status: "PENDING_REVIEW",
            actor: "analyst",
            detail: { transport: "sftp_configured", note: "Awaiting compliance approval before SFTP queue." },
            stack_trace: null,
            created_at: ts,
          },
        ],
      },
    ];
  }
  return mockSarIntentStore[caseId]!;
}

export function getMockResponse(url: string, init?: RequestInit): unknown | null {
  if (import.meta.env.PROD) {
    throw new Error("getMockResponse must not run in production builds.");
  }
  const method = (init?.method ?? "GET").toUpperCase();
  const path = parsePath(url);
  const body = safeParseRequestBody(init);

  if (path === "/api/v1/demo/simulate_attack" && method === "POST") {
    const n = 4;
    const results = Array.from({ length: n }, (_, i) => ({
      pattern_index: i,
      total: n,
      transaction_id: `sim-${mockRandomAlpha(12)}`,
      amount: 10 + i * 5,
      currency: "USD",
      channel: "card_not_present",
      shadow_verdict: i % 2 === 0 ? "FLAG" : "ALLOW",
      integrity_confidence: Math.min(0.95, 0.5 + i * 0.11),
    }));
    return { total: n, results };
  }

  if (path.includes("/api/core/v1/omni-search") && method === "GET") {
    return {
      entities: [
        { entity_id: "ent_acme_1", tenant_id: "demo", label: "ent_acme_1", subtitle: "tenant demo" },
      ],
      cases: [
        {
          id: "550e8400-e29b-41d4-a716-446655440000",
          tenant_id: "demo",
          title: "Acme investigation",
          entity_id: "ent_acme_1",
          trace_id: "tr-001",
          status: "open",
          label: "Acme investigation",
          subtitle: "ent_acme_1 · tr-001",
        },
      ],
      rules: [
        {
          rule_id: "high_amount_payment",
          pack_file: "default.json",
          pack_name: "Default",
          label: "high_amount_payment",
          subtitle: "High amount",
        },
      ],
    };
  }

  if (path.includes("/api/investigation/v1/governance") && method === "GET") {
    return {
      profile: "global",
      label: "Global",
      references: [
        "ISO/IEC 42001 (AI management systems — optional certification path)",
        "OECD AI Principles",
        "Contractual and local statutory requirements (varies by country)",
      ],
      batch_ttl_seconds: 7200,
      disclaimer:
        "Reference list is illustrative. Validate deployment against your counsel, DPA, and sector rules.",
    };
  }

  if (path.includes("/api/investigation/v1/knowledge/ingest") && method === "POST") {
    return {
      doc_id: "00000000-0000-4000-8000-0000000000aa",
      title: String((body as AnyObj).title ?? "untitled").slice(0, 256),
      ttl_hours: 2,
      docs_stored_for_scope: 1,
      embeddings_stored: false,
    };
  }

  if (path.includes("/api/investigation/v1/feedback/summary") && method === "GET") {
    const tid = new URL(url, "http://localhost").searchParams.get("tenant_id") ?? "demo";
    return {
      tenant_id: tid,
      window_days: 7,
      total: 0,
      by_rating: { "-1": 0, "0": 0, "1": 0 },
      avg_rating: null,
    };
  }

  if (path.includes("/api/investigation/v1/feedback/recent") && method === "GET") {
    return { items: [] };
  }

  if (path.includes("/api/investigation/v1/feedback") && method === "POST") {
    return { ok: true, stored: true, feedback_id: 1 };
  }

  if (path.includes("/api/investigation/v1/playbooks") && method === "GET") {
    return {
      playbooks: [
        { id: "account_takeover", title: "Account takeover (ATO)", vertical: "fintech" },
        { id: "aml_escalation", title: "AML & fincrime escalation (facts vs suspicion)", vertical: "aml_fincrime" },
        { id: "collusion_fake_accounts", title: "Collusion, fake & duplicate accounts", vertical: "platform_abuse" },
        { id: "coupon_instrument_abuse", title: "Coupon, stacking & instrument-led promo abuse", vertical: "ecommerce_promo" },
        { id: "disputes_chargebacks", title: "Disputes & chargebacks (lifecycle + evidence)", vertical: "payments_disputes" },
        { id: "fulfillment_inrb_snad", title: "Fulfillment — INR, SNAD, damage, theft claims", vertical: "ecommerce_logistics" },
        { id: "mule_layering", title: "Money mule & layering indicators", vertical: "payments_fincrime" },
        { id: "payments_first_party", title: "Payments — first-party / friendly fraud", vertical: "payments" },
        { id: "refund_promo_abuse", title: "Refund & promo abuse", vertical: "ecommerce_food_delivery" },
        { id: "scheme_monitoring_merchant", title: "Scheme-style monitoring (fraud + disputes + testing)", vertical: "payments_acquiring" },
      ],
    };
  }

  if (path.includes("/api/investigation/v1/batch/ingest") && method === "POST") {
    return {
      batch_id: "00000000-0000-4000-8000-000000000099",
      filename: "demo-upload.csv",
      format: "csv",
      row_count: 3,
      columns: ["entity_id", "amount_cents", "risk_flag"],
      sample_rows: [
        { entity_id: "e1", amount_cents: "1200", risk_flag: "high" },
        { entity_id: "e2", amount_cents: "99", risk_flag: "low" },
        { entity_id: "e3", amount_cents: "5000", risk_flag: "high" },
      ],
      limits: { max_rows_stored: 8000, max_file_mib: 15, ttl_hours: 2 },
    };
  }

  if (path.includes("/api/decisions/v1/ml/export/pit-parquet/jobs/") && method === "GET") {
    const parts = path.split("/").filter(Boolean);
    const jobId = parts[parts.length - 1] ?? "unknown";
    const prev = pitParquetMockJobPolls.get(jobId) ?? 0;
    const n = prev + 1;
    pitParquetMockJobPolls.set(jobId, n);
    if (n >= 5) {
      pitParquetMockJobPolls.delete(jobId);
      return {
        job_id: jobId,
        status: "SUCCEEDED",
        progress_pct: 100,
        rows_written: 12_500,
        chunks_processed: 5,
        max_rows: 500_000,
        error: null,
        result: {
          rows_written: 12_500,
          chunks_processed: 5,
          local_path: "/tmp/mock-pit-export.parquet",
          artifact_uri: "file:///tmp/mock-pit-export.parquet",
          presigned_get_url: null,
          pit_note:
            "Features are taken only from warehouse payload_json at ingest (evaluation_time = created_at). Labels come from case-api disputes / case labels by trace_id.",
        },
      };
    }
    return {
      job_id: jobId,
      status: n <= 1 ? "PENDING" : "RUNNING",
      progress_pct: Math.min(95, n * 18),
      rows_written: n * 2400,
      chunks_processed: Math.max(0, n - 1),
      max_rows: 500_000,
      error: null,
      result: null,
    };
  }

  if (path.includes("/api/decisions/v1/ml/export/pit-parquet/jobs") && method === "POST") {
    const jid = `mock-pit-${mockRandomAlpha(10)}`;
    pitParquetMockJobPolls.set(jid, 0);
    return { job_id: jid, status: "PENDING" };
  }

  if (path.includes("/api/ingress/v1/compliance/residency/audit/export.csv")) {
    return [
      "id,tenant_id,component,vendor_key,tenant_region,vendor_region,outcome,detail,request_url_preview,created_at",
      `mock-row-1,demo,osint,shodan,EU,US,compliance_block,"Synthetic mock row",https://example.test/mock,${nowIso()}`,
    ].join("\n");
  }

  if (path.includes("/api/ingress/v1/compliance/residency/audit") && method === "GET" && !path.includes("export.csv")) {
    return {
      items: [
        {
          id: "mock-row-1",
          tenant_id: "demo",
          component: "osint",
          vendor_key: "shodan",
          tenant_region: "EU",
          vendor_region: "US",
          outcome: "compliance_block",
          detail: "Synthetic mock row (VITE_USE_API_MOCKS)",
          request_url_preview: "https://example.test/mock",
          created_at: nowIso(),
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
      has_more: false,
    };
  }

  if (path.includes("/api/ingress/v1/compliance/residency/matrix")) {
    if (method === "GET") {
      return mockResidencyMatrixPayload();
    }
    if (method === "PUT") {
      const tid = String((body as AnyObj).tenant_id ?? "").trim();
      const vk = String((body as AnyObj).vendor_key ?? "").trim();
      const blocked = Boolean((body as AnyObj).blocked);
      if (!tid || !vk) {
        return null;
      }
      const ck = `${tid}::${vk}`;
      if (blocked) {
        residencyMatrixMockCells[ck] = true;
      } else {
        delete residencyMatrixMockCells[ck];
      }
      return { ok: true, ...mockResidencyMatrixPayload() };
    }
  }

  if (path.includes("/api/decisions/v1/replay") && method === "POST") {
    const body = safeParseRequestBody(init);
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
        { policy_id: "default_v1", version: 1, description: "Default escalation ladder" },
        { policy_id: "strict_review_v1", version: 1, description: "Stricter review thresholds" },
      ],
    };
  }
  if (path.includes("/api/cases/v1/health")) {
    return {
      status: "ok",
      database_backend: "postgresql",
      database_url: "postgresql+asyncpg://fraud:***@localhost:5432/fraud_cases",
      database_fallback_active: false,
      database_fallback_reason: null,
      database_bootstrap_mode: "alembic_head",
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
  if (path.includes("/api/ingest/v1/ingest/stats") && method === "GET") {
    return {
      service: "event-ingest",
      since: "process_boot",
      envelope_mode: "optional",
      require_idempotency_key: false,
      contract_reject_by_reason: {
        ingest_event_type_invalid: 2,
        ingest_idempotency_key_required: 1,
      },
      total_contract_rejects: 3,
      note: "Demo totals for offline UI; live service may return zeros until contract validation rejects traffic.",
    };
  }
  if (path.includes("/evidence-bundle")) {
    return {
      bundle_version: "1",
      tenant_id: "demo",
      case: { id: "case-demo", title: "Demo case", trace_id: "tr-demo" },
      decision_audit: { trace_id: "tr-demo", decision: "review", score: 74 },
      bundle_signature: "mock",
      signing_key_id: "mock",
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

  if (path.includes("/api/cases/v1/cases/ops/sar-transport/board")) {
    const qs = path.includes("?") ? path.split("?")[1] : "";
    const tid = new URLSearchParams(qs).get("tenant_id") ?? "demo";
    const now = nowIso();
    return {
      schema: "tarka.sar_transport_board/v1",
      tenant_id: tid,
      status_mapping: {
        pending_db_statuses: ["FILED", "APPROVED"],
        claimed_db_statuses: ["SFTP_QUEUED"],
        uploaded_db_statuses: ["TRANSMITTED", "ACKNOWLEDGED"],
        failed_db_statuses: ["FAILED"],
        note: "Mock board for offline UI.",
      },
      columns: {
        pending: {
          count: 1,
          items: [
            {
              id: "00000000-0000-4000-8000-000000000001",
              tenant_id: tid,
              case_id: "00000000-0000-4000-8000-000000000002",
              status: "FILED",
              sar_artifact_id: "00000000-0000-4000-8000-000000000003",
              created_at: now,
              updated_at: now,
            },
          ],
        },
        claimed: {
          count: 1,
          items: [
            {
              id: "00000000-0000-4000-8000-000000000011",
              tenant_id: tid,
              case_id: "00000000-0000-4000-8000-000000000012",
              status: "SFTP_QUEUED",
              sar_artifact_id: "00000000-0000-4000-8000-000000000013",
              created_at: now,
              updated_at: now,
            },
          ],
        },
        uploaded: {
          count: 1,
          items: [
            {
              id: "00000000-0000-4000-8000-000000000021",
              tenant_id: tid,
              case_id: "00000000-0000-4000-8000-000000000022",
              status: "ACKNOWLEDGED",
              sar_artifact_id: "00000000-0000-4000-8000-000000000023",
              created_at: now,
              updated_at: now,
            },
          ],
        },
      },
      failed: { count: 0, items: [] },
    };
  }
  if (path.includes("/api/cases/v1/cases/ops/sar-transport/force-sftp-sync") && method === "POST") {
    return { ok: true, published: true, processed_one: false, cooldown_seconds: 60 };
  }
  if (path.includes("/api/cases/v1/cases/ops/kpis")) {
    return {
      tenant_id: "demo",
      total_cases: mockCases.length,
      queue_score_avg: 85,
      critical_open: 1,
      investigating_rate: 0.4,
      resolved_rate: 0.2,
      median_case_age_hours: 6.5,
      by_status: { open: 2, investigating: 1, closed: 1 } as Record<string, number>,
      sla_breached_open_or_investigating: 0,
      label_boost_cases: 1,
    };
  }
  if (path.includes("/api/cases/v1/cases/ops/desk-activity")) {
    return {
      tenant_id: "demo",
      period_days: 7,
      since: new Date(Date.now() - 7 * 86400000).toISOString(),
      touch_actions_total: 4,
      by_action: { update_case: 2, add_comment: 1, update_labels: 1 },
      recent: [
        {
          id: "a1",
          action: "update_case",
          actor: "analyst@demo",
          resource_id: "c1",
          created_at: nowIso(),
        },
      ],
    };
  }
  if (path.includes("/api/cases/v1/cases/analytics/cohort-compare")) {
    return {
      tenant_id: "demo",
      period_days: 7,
      cases_created_recent: 12,
      cases_created_prior: 10,
      delta: 2,
      delta_percent_vs_prior: 20,
    };
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
    const caseIds = Array.isArray((body as AnyObj).case_ids) ? ((body as AnyObj).case_ids as unknown[]) : [];
    return { updated: caseIds.length, items: mockCases };
  }
  if (path.includes("/api/cases/v1/cases/") && path.includes("/playbooks/") && method === "POST") {
    return { ok: true, playbook: "demo", case: mockCases[0] };
  }
  if (path.match(/\/api\/cases\/v1\/cases\/[^/]+\/graph/)) {
    return {
      nodes: [
        { id: "fraud_frank", labels: ["User"], properties: { risk: "high" } },
        { id: "dev_emulator_003", labels: ["Device"], properties: { is_emulator: true } },
      ],
      edges: [{ from_id: "fraud_frank", to_id: "dev_emulator_003", type: "USED", properties: { shared: true } }],
    };
  }
  if (path.match(/\/api\/cases\/v1\/cases\/[^/]+\/decision-explanation/)) {
    const caseId = path.split("/").slice(-2, -1)[0] ?? "c1";
    return {
      case_id: caseId,
      trace_id: "tr-1001",
      entity_id: "fraud_frank",
      source: "decision_audit",
      decision: "deny",
      score: 92,
      graph_decision_explanation: {
        schema_id: "tarka.graph_decision_explanation/v1",
        factors: [
          { factor_id: "shared_device_ring", weight: 0.73 },
          { factor_id: "velocity_burst", weight: 0.62 },
        ],
        why_links: [{ from_factor_id: "velocity_burst", to_artifact_id: "tr-1001" }],
      },
    };
  }
  if (path.match(/\/api\/cases\/v1\/cases\/[^/]+\/sar\/intents(\?|$)/) && method === "GET") {
    const m = path.match(/\/cases\/([^/]+)\/sar\/intents/);
    const caseId = m?.[1] ?? "c1";
    return { case_id: caseId, intents: ensureMockSarIntents(caseId) };
  }
  if (path.match(/\/sar\/intents\/[^/]+\/approve/) && method === "POST") {
    const m = path.match(/\/cases\/([^/]+)\/sar\/intents\/([^/]+)\/approve/);
    const caseId = m?.[1] ?? "c1";
    const intentId = m?.[2] ?? "";
    const humanActor = assertHumanActorIdForSarFiling(body);
    const intents = ensureMockSarIntents(caseId);
    const intent = intents.find((x) => x.id === intentId) as AnyObj | undefined;
    if (!intent) return { sar_filing_intent_id: intentId, status: "PENDING_REVIEW" };
    if (intent.status === "FILED") return { sar_filing_intent_id: intentId, status: "FILED" };
    if (intent.status === "APPROVED") return { sar_filing_intent_id: intentId, status: "APPROVED" };
    if (intent.status === "PENDING_REVIEW") {
      const ts = nowIso();
      intent.status = "FILED";
      intent.updated_at = ts;
      const log = intent.audit_log as AnyObj[];
      log.push({
        id: id("aud"),
        from_status: "PENDING_REVIEW",
        to_status: "FILED",
        actor: humanActor,
        detail: { reason_code: "SAR_APPROVED_FOR_FILING" },
        stack_trace: null,
        created_at: ts,
      });
    }
    return { sar_filing_intent_id: intentId, status: intent.status };
  }
  if (path.match(/\/sar\/intents\/[^/]+\/queue-sftp/) && method === "POST") {
    const m = path.match(/\/cases\/([^/]+)\/sar\/intents\/([^/]+)\/queue-sftp/);
    const caseId = m?.[1] ?? "c1";
    const intentId = m?.[2] ?? "";
    const intents = ensureMockSarIntents(caseId);
    const intent = intents.find((x) => x.id === intentId) as AnyObj | undefined;
    if (!intent) return { sar_filing_intent_id: intentId, status: "PENDING_REVIEW" };
    if (intent.status === "SFTP_QUEUED") return { sar_filing_intent_id: intentId, status: "SFTP_QUEUED" };
    if (intent.status === "FILED" || intent.status === "APPROVED") {
      const ts = nowIso();
      const fromStatus = intent.status as string;
      intent.status = "SFTP_QUEUED";
      intent.updated_at = ts;
      const log = intent.audit_log as AnyObj[];
      log.push({
        id: id("aud"),
        from_status: fromStatus,
        to_status: "SFTP_QUEUED",
        actor: "analyst",
        detail: { reason_code: "SAR_SFTP_QUEUED" },
        stack_trace: null,
        created_at: ts,
      });
    }
    return { sar_filing_intent_id: intentId, status: intent.status };
  }
  if (path.match(/\/cases\/([^/]+)\/sar\/intents\/([^/]+)\/detail(\?|$)/) && method === "GET") {
    const m = path.match(/\/cases\/([^/]+)\/sar\/intents\/([^/]+)\/detail/);
    const caseId = m?.[1] ?? "c1";
    const intentId = m?.[2] ?? "";
    const intents = ensureMockSarIntents(caseId);
    const intent = intents.find((x) => x.id === intentId) as AnyObj | undefined;
    if (!intent) {
      return {
        case_id: caseId,
        intent_id: intentId,
        status: "PENDING_REVIEW",
        sar_artifact_id: null,
        created_at: nowIso(),
        updated_at: nowIso(),
        investigative_notes_html: "",
        notes_editor_locked: false,
        fincen_submission_sha256_hex: null,
        audit_log: [],
      };
    }
    const locked = intent.status === "TRANSMITTED" || intent.status === "ACKNOWLEDGED";
    const sha =
      locked
        ? "a".repeat(64)
        : null;
    return {
      case_id: caseId,
      intent_id: intentId,
      status: intent.status,
      sar_artifact_id: intent.sar_artifact_id ?? null,
      created_at: intent.created_at ?? nowIso(),
      updated_at: intent.updated_at ?? nowIso(),
      investigative_notes_html: String(intent.investigative_notes_html ?? ""),
      notes_editor_locked: locked,
      fincen_submission_sha256_hex: sha,
      audit_log: intent.audit_log ?? [],
    };
  }
  if (path.match(/\/sar\/intents\/[^/]+\/investigative-notes/) && method === "PATCH") {
    const m = path.match(/\/cases\/([^/]+)\/sar\/intents\/([^/]+)\/investigative-notes/);
    const caseId = m?.[1] ?? "c1";
    const intentId = m?.[2] ?? "";
    const intents = ensureMockSarIntents(caseId);
    const intent = intents.find((x) => x.id === intentId) as AnyObj | undefined;
    if (!intent) {
      return { ok: true, intent_id: intentId, notes_editor_locked: false, investigative_notes_html: "" };
    }
    if (intent.status === "TRANSMITTED" || intent.status === "ACKNOWLEDGED") {
      return null;
    }
    const html = typeof body.notes_html === "string" ? body.notes_html : "";
    intent.investigative_notes_html = html;
    intent.updated_at = nowIso();
    return {
      ok: true,
      intent_id: intentId,
      notes_editor_locked: false,
      investigative_notes_html: html,
    };
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
    return {
      nodes: [
        {
          id: "fraud_frank",
          labels: ["User"],
          properties: { risk: "high", device_hash: "devhx_bot_01" },
        },
        { id: "acct_ring_a", labels: ["User"], properties: { device_hash: "devhx_bot_01" } },
        { id: "acct_ring_b", labels: ["User"], properties: { device_hash: "devhx_bot_01" } },
        { id: "acct_ring_c", labels: ["User"], properties: { device_hash: "devhx_bot_01" } },
        { id: "dev_emulator_003", labels: ["Device"], properties: { is_emulator: true, device_hash: "unique_dev" } },
        { id: "ip_shared", labels: ["IP"], properties: {} },
      ],
      edges: [
        { from_id: "fraud_frank", to_id: "ip_shared", type: "FROM" },
        { from_id: "acct_ring_a", to_id: "ip_shared", type: "FROM" },
        { from_id: "acct_ring_b", to_id: "ip_shared", type: "FROM" },
        { from_id: "acct_ring_c", to_id: "ip_shared", type: "FROM" },
        { from_id: "fraud_frank", to_id: "dev_emulator_003", type: "USED", properties: { shared: true } },
      ],
    };
  }
  if (path.includes("/api/graph/v1/entities/") && path.includes("/deep-context")) {
    const m = path.match(/\/entities\/([^/]+)\/deep-context/);
    const ext = m ? decodeURIComponent(m[1]) : "unknown";
    if (ext === "__missing__") {
      return { not_found: true };
    }
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    return {
      entity_id: ext,
      tenant_id: tid,
      historical_transactions: [
        {
          external_id: "pay_demo_1",
          trace_id: "tr-1001",
          amount: 49.99,
          currency: "USD",
          decision: "review",
          ip: "198.51.100.2",
          occurred_at: nowIso(),
        },
      ],
      ip_addresses: [
        { ip: "198.51.100.2", source: "property:client_ip", last_seen: nowIso(), event_count: 3 },
        { ip: "203.0.113.9", source: "demo_neighbor", last_seen: null, event_count: 1 },
      ],
      risk_history: [
        {
          recorded_at: nowIso(),
          risk_score: 0.88,
          risk_factors: ["shared_device", "velocity"],
          source: "current_entity_risk",
        },
      ],
    };
  }
  if (path.includes("/api/graph/v1/analytics/entity-risk")) {
    return { entity_id: "fraud_frank", risk_score: 0.94, risk_factors: ["shared_device", "velocity"], connected_flagged_count: 4, community_size: 6 };
  }
  if (path.includes("/api/graph/v1/analytics/communities")) return { communities: [{ community_id: 1, member_count: 6, member_ids: ["fraud_frank"], member_labels: ["User"], shared_attributes: ["device"] }] };
  if (path.includes("/api/graph/v1/analytics/risk-propagation")) {
    const u = new URL(url, "http://localhost");
    const seed = u.searchParams.get("entity_id") ?? "fraud_frank";
    return {
      entities: [
        {
          entity_id: seed,
          entity_labels: ["User"],
          propagated_risk_score: 0.91,
          distance: 0,
          path_description: `${seed} (anchor)`,
        },
        {
          entity_id: "dev_emulator_003",
          entity_labels: ["Device"],
          propagated_risk_score: 0.72,
          distance: 1,
          path_description: `${seed} -> dev_emulator_003`,
        },
        {
          entity_id: "ip_shared",
          entity_labels: ["IP"],
          propagated_risk_score: 0.68,
          distance: 1,
          path_description: `${seed} -> ip_shared`,
        },
        {
          entity_id: "acct_ring_a",
          entity_labels: ["User"],
          propagated_risk_score: 0.55,
          distance: 2,
          path_description: `gremlin:bfs:${seed}->acct_ring_a`,
        },
        {
          entity_id: "fraud_gina",
          entity_labels: ["User"],
          propagated_risk_score: 0.48,
          distance: 2,
          path_description: `${seed} -> ip_shared -> fraud_gina`,
        },
      ],
    };
  }
  if (path.includes("/api/graph/v1/analytics/fraud-rings")) return { rings: [{ ring_members: ["fraud_frank", "fraud_gina"], ring_size: 2, relationships: ["COLLABORATES_WITH"], aggregate_tags: ["ring"] }] };

  if (path.includes("/api/analytics/v1/analytics/decisions")) {
    const rows = buildMockAnalyticsDecisionRows();
    return { rows, total: rows.length };
  }
  if (path.includes("/api/analytics/v1/analytics/hourly")) return { rows: [{ hour: nowIso(), decision: "deny", event_count: 12, avg_score: 83, deny_count: 6, review_count: 4, allow_count: 2 }] };
  if (path.includes("/api/analytics/v1/analytics/top-entities")) return { decision: "deny", entities: [{ entity_id: "fraud_frank", cnt: 11, avg_score: 91, sample_traces: ["tr-1001"] }] };
  if (path.includes("/api/analytics/v1/analytics/scorecard")) {
    return {
      tenant_id: "demo",
      window_days: 7,
      total_events: 120,
      deny_rate_pct: 23.33,
      per_decision: [
        {
          decision: "deny",
          event_count: 28,
          event_pct: 23.33,
          avg_score: 88.2,
          min_score: 42,
          max_score: 99,
        },
        {
          decision: "review",
          event_count: 45,
          event_pct: 37.5,
          avg_score: 62.1,
          min_score: 35,
          max_score: 91,
        },
        {
          decision: "allow",
          event_count: 47,
          event_pct: 39.17,
          avg_score: 28.4,
          min_score: 5,
          max_score: 72,
        },
      ],
      top_rule_hits: [
        { rule_id: "velocity_spike", hit_count: 41 },
        { rule_id: "new_device", hit_count: 22 },
      ],
    };
  }

  if (path.includes("/api/ml/v1/health")) {
    return {
      status: "ok",
      disable_ml: false,
      model_version: "heuristic-v1",
      onnx_loaded: false,
      registry_models: 1,
      shap_stretch_enabled: false,
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
  if (path.includes("/api/decisions/v1/rules/change-log")) {
    return {
      items: [
        { ts: new Date().toISOString(), action: "create", file: "pack_abc.json", actor: "mock", detail: {} },
      ],
      path: "rules/rule_change_log.jsonl",
      count: 1,
    };
  }
  if (path.includes("/api/rule-engine/v1/rules/versions/") && method === "GET") {
    const ver = Number(path.split("/").pop()?.split("?")[0]);
    const row = MOCK_RULE_AST_VERSIONS.find((v) => v.version === ver);
    if (!row) return { error: "not_found" };
    return {
      version: row.version,
      is_active: row.version === mockRuleEngineActiveVersion,
      rule_count: row.rule_count,
      created_at: row.created_at,
      ast_hash: row.ast_hash,
      rules_payload: row.rules_payload,
    };
  }
  if (path.includes("/api/rule-engine/v1/rules/rollback/") && method === "POST") {
    const ver = Number(path.split("/").pop()?.split("?")[0]);
    if (!MOCK_RULE_AST_VERSIONS.some((v) => v.version === ver)) return { error: "not_found" };
    mockRuleEngineActiveVersion = ver;
    const row = MOCK_RULE_AST_VERSIONS.find((v) => v.version === ver)!;
    return { ok: true, active_version: ver, rule_count: row.rule_count, reloaded: true };
  }
  if (path.includes("/api/rule-engine/v1/rules/versions") && method === "GET") {
    const versions = MOCK_RULE_AST_VERSIONS.map((v) => ({
      version: v.version,
      is_active: v.version === mockRuleEngineActiveVersion,
      rule_count: v.rule_count,
      created_at: v.created_at,
      ast_hash: v.ast_hash,
    }));
    return { versions, active_version: mockRuleEngineActiveVersion, source: "mock" };
  }
  if (path.includes("/api/rule-engine/v1/rules/reload") && method === "POST") {
    const row = MOCK_RULE_AST_VERSIONS.find((v) => v.version === mockRuleEngineActiveVersion);
    return { ok: true, count: row?.rule_count ?? 0 };
  }

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
  if (path.includes("/api/ingress/v1/ops/failover-toggles")) {
    if (method === "PUT" && body && typeof body === "object") {
      const b = body as Record<string, unknown>;
      mockFailoverToggles = {
        graph_plane_disabled: Boolean(b.graph_plane_disabled),
        ai_plane_disabled: Boolean(b.ai_plane_disabled),
        updated_by: typeof b.actor_id === "string" ? b.actor_id : "analyst-mock",
      };
    }
    const st = mockFailoverToggles;
    const t = Date.now();
    const wave = (t / 5000) % 1;
    const graphMs = 120 + Math.sin(wave * Math.PI * 2) * 280;
    const aiMs = 400 + Math.sin(wave * Math.PI * 2 + 0.8) * 900;
    return {
      graph_plane_disabled: Boolean(st.graph_plane_disabled),
      ai_plane_disabled: Boolean(st.ai_plane_disabled),
      graph_latency_ms_p95: Math.round(graphMs),
      ai_latency_ms_p95: Math.round(aiMs),
      updated_at: nowIso(),
      updated_by: st.updated_by,
      source: "mock",
    };
  }

  if (path.includes("/api/ingress/v1/marketplace/webhook-logs/") && path.includes("/retry") && method === "POST") {
    const logId = path.split("/").find((p, i, a) => a[i - 1] === "webhook-logs") ?? "";
    const row = mockMarketplaceWebhookLogs.find((l) => l.id === logId);
    if (!row) return { error: "not_found" };
    row.status = "delivered";
    row.http_status = 200;
    row.latency_ms = 42;
    row.delivered_at = nowIso();
    row.last_error = null;
    row.attempt_count += 1;
    return { ok: true, log: { ...row, payload: { signal: "block", decision: "BLOCK" }, attempts: [] } };
  }
  if (path.includes("/api/ingress/v1/marketplace/webhook-logs/") && method === "GET" && !path.endsWith("/webhook-logs")) {
    const logId = path.split("/").pop()?.split("?")[0] ?? "";
    const row = mockMarketplaceWebhookLogs.find((l) => l.id === logId);
    if (!row) return { error: "not_found" };
    return {
      ...row,
      payload: {
        signal: "block",
        decision: "BLOCK",
        tenant_id: row.tenant_id,
        user_id: row.user_id,
        entity_id: row.entity_id,
        trace_id: row.trace_id,
        blocking_rule_id: "rule_velocity_burst",
      },
      attempts: [
        {
          attempt: 1,
          status_code: row.http_status,
          error: row.last_error,
          latency_ms: row.latency_ms,
          timestamp: row.created_at,
        },
      ],
    };
  }
  if (path.includes("/api/ingress/v1/marketplace/webhook-logs") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const st = (u.searchParams.get("status") ?? "").toLowerCase();
    let items = mockMarketplaceWebhookLogs.filter((l) => l.tenant_id === tid);
    if (st) items = items.filter((l) => l.status === st);
    const delivered = items.filter((l) => l.status === "delivered").length;
    const failed = items.filter((l) => l.status === "failed" || l.status === "dlq").length;
    return {
      tenant_id: tid,
      items,
      count: items.length,
      summary: { delivered, failed, pending: items.length - delivered - failed },
    };
  }

  if (path.includes("/api/ingress/v1/compliance/pii-field-reveal/audit") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const items = mockPiiRevealAudit.filter((e) => e.tenant_id === tid).slice(0, 50);
    const reveals = items.filter((e) => e.action === "reveal").length;
    return { tenant_id: tid, items, count: items.length, summary: { reveals } };
  }
  if (path.includes("/api/ingress/v1/compliance/pii-field-reveal") && method === "POST") {
    const b = (body ?? {}) as Record<string, unknown>;
    const row = {
      id: `pii-${id("r")}`,
      tenant_id: String(b.tenant_id ?? "demo"),
      actor_id: "analyst-mock",
      action: String(b.action ?? "reveal"),
      field_kind: String(b.field_kind ?? "generic"),
      field_path: String(b.field_path ?? "unknown"),
      context_type: String(b.context_type ?? "ui"),
      context_id: b.context_id != null ? String(b.context_id) : null,
      value_fingerprint: String(b.value_fingerprint ?? "00000000"),
      masked_preview: String(b.masked_preview ?? "****"),
      created_at: nowIso(),
    };
    mockPiiRevealAudit = [row, ...mockPiiRevealAudit].slice(0, 200);
    return { ok: true, event: row };
  }

  if (path.includes("/api/ingress/v1/marketplace/rate-limit-shields/") && method === "PATCH") {
    const parts = path.split("/");
    const keyId = parts[parts.indexOf("rate-limit-shields") + 1]?.split("?")[0] ?? "";
    const b = (body ?? {}) as Record<string, unknown>;
    const tid = String(b.tenant_id ?? "demo");
    const row = mockMarketplaceSdkKeys.find((k) => k.id === keyId && k.tenant_id === tid);
    if (!row) return { error: "not_found" };
    if (b.enabled != null) row.rate_limit_enabled = Boolean(b.enabled);
    if (b.requests_per_minute != null) row.rate_limit_rpm = Number(b.requests_per_minute);
    if (b.burst != null) row.rate_limit_burst = Number(b.burst);
    mockRateLimitLive[keyId] = {
      requests_in_window: 0,
      remaining: row.rate_limit_burst ?? 50,
      throttled: false,
      rejected_total: mockRateLimitLive[keyId]?.rejected_total ?? 0,
    };
    return { ok: true, shield: mockShieldItemFromKey(row) };
  }
  if (path.includes("/api/ingress/v1/marketplace/rate-limit-shields") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const items = mockMarketplaceSdkKeys.filter((k) => k.tenant_id === tid).map(mockShieldItemFromKey);
    const throttled = items.filter((i) => i.live.throttled).length;
    const enabled = items.filter((i) => i.shield.enabled).length;
    return { tenant_id: tid, items, count: items.length, summary: { throttled, shields_enabled: enabled } };
  }

  if (path.includes("/api/ingress/v1/marketplace/sdk-api-keys/catalog") && method === "GET") {
    return {
      platforms: MOCK_SDK_PLATFORMS,
      allowed_scopes: ["evaluate", "ingest", "attestation", "marketplace_profile", "shadow_read"],
    };
  }
  if (path.includes("/api/ingress/v1/marketplace/sdk-api-keys/") && path.includes("/revoke") && method === "POST") {
    const parts = path.split("/");
    const keyId = parts[parts.indexOf("sdk-api-keys") + 1]?.split("?")[0] ?? "";
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const row = mockMarketplaceSdkKeys.find((k) => k.id === keyId && k.tenant_id === tid);
    if (!row) return { error: "not_found" };
    row.status = "revoked";
    return { ok: true, key: row };
  }
  if (path.includes("/api/ingress/v1/marketplace/sdk-api-keys") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const keys = mockMarketplaceSdkKeys.filter((k) => k.tenant_id === tid).map((k) => ({
      ...k,
      rate_limit: {
        enabled: k.rate_limit_enabled !== false,
        requests_per_minute: k.rate_limit_rpm ?? 600,
        burst: k.rate_limit_burst ?? 50,
      },
    }));
    return { tenant_id: tid, keys, count: keys.length };
  }
  if (path.includes("/api/ingress/v1/marketplace/sdk-api-keys") && method === "POST") {
    const b = (body ?? {}) as Record<string, unknown>;
    const tid = String(b.tenant_id ?? "demo");
    const platform = String(b.platform ?? "sdk-typescript");
    const label = String(b.label ?? "New SDK key");
    const scopes = Array.isArray(b.scopes) ? b.scopes.map(String) : ["evaluate", "ingest"];
    const secret = `tarka_mkt_${Math.random().toString(36).slice(2, 10)}${Math.random().toString(36).slice(2, 10)}`;
    const row = {
      id: `msk-${id("k")}`,
      tenant_id: tid,
      platform,
      label,
      key_prefix: `tarka_mkt_${secret.slice(10, 14)}…${secret.slice(-4)}`,
      scopes,
      status: "active",
      created_at: nowIso(),
      last_used_at: null,
      created_by: "analyst-mock",
      rate_limit_enabled: true,
      rate_limit_rpm: 600,
      rate_limit_burst: 50,
    };
    mockMarketplaceSdkKeys = [row, ...mockMarketplaceSdkKeys];
    mockRateLimitLive[row.id] = { requests_in_window: 0, remaining: 50, throttled: false, rejected_total: 0 };
    return {
      ok: true,
      key: {
        ...row,
        rate_limit: { enabled: true, requests_per_minute: 600, burst: 50 },
      },
      secret,
      warning: "Copy the secret now — it will not be shown again.",
    };
  }

  if (path.includes("/api/ingress/v1/ops/automated-backup-indicators") && method === "GET") {
    const t = Date.now();
    const pgAgeH = 4 + (Math.sin((t / 60000) % (Math.PI * 2)) + 1) * 2;
    const jgAgeH = 6 + (Math.sin((t / 60000) % (Math.PI * 2) + 1) + 1) * 3;
    const pgAt = new Date(t - pgAgeH * 3600_000).toISOString();
    const jgAt = new Date(t - jgAgeH * 3600_000).toISOString();
    const pgStatus = pgAgeH <= 26 ? "ok" : pgAgeH <= 50 ? "warn" : "stale";
    const jgStatus = jgAgeH <= 26 ? "ok" : jgAgeH <= 50 ? "warn" : "stale";
    return {
      updated_at: nowIso(),
      backup_dir: "data/backups",
      thresholds_hours: { ok: 26, warn: 50 },
      schedule_hints: {
        postgres: "Daily 02:00 UTC (pg_dump)",
        janusgraph: "Daily 03:30 UTC (gremlin backup)",
      },
      stores: [
        {
          store: "postgres",
          label: "PostgreSQL",
          last_snapshot_at: pgAt,
          age_seconds: Math.round(pgAgeH * 3600),
          status: pgStatus,
          artifact_hint: "postgres/nightly-20260517.sql.gz",
          size_bytes: 1_842_000_000,
          source: "mock",
          schedule_hint: "Daily 02:00 UTC (pg_dump)",
        },
        {
          store: "janusgraph",
          label: "JanusGraph",
          last_snapshot_at: jgAt,
          age_seconds: Math.round(jgAgeH * 3600),
          status: jgStatus,
          artifact_hint: "janusgraph/gremlin-backup-20260517.tar.gz",
          size_bytes: 512_000_000,
          source: "mock",
          schedule_hint: "Daily 03:30 UTC (gremlin backup)",
        },
      ],
    };
  }

  if (path.includes("/api/ingress/v1/ops/nats-dead-letter-office") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const kindFilter = (u.searchParams.get("kind") ?? "").toLowerCase();
    const tenantFilter = (u.searchParams.get("tenant_id") ?? "").toLowerCase();
    const allItems = [
      {
        id: "10482",
        sequence: 10482,
        subject: "fraud.events.dlq",
        received_at: null,
        kind: "evaluate_4xx",
        status_code: 422,
        tenant_id: "demo",
        entity_id: "ent_mkt_4412",
        event_type: "card_not_present",
        nats_source_subject: "fraud.events.card_not_present",
        preview: '{"kind":"evaluate_4xx","status_code":422}',
        envelope: {
          schema_version: "1",
          kind: "evaluate_4xx",
          status_code: 422,
          nats_source_subject: "fraud.events.card_not_present",
          event: { tenant_id: "demo", entity_id: "ent_mkt_4412", event_type: "card_not_present", amount: 1840 },
          evaluate_request: { tenant_id: "demo", entity_id: "ent_mkt_4412", event_type: "card_not_present" },
          evaluate_response_preview: '{"detail":"rule pack version mismatch"}',
        },
      },
      {
        id: "10481",
        sequence: 10481,
        subject: "fraud.events.dlq",
        received_at: null,
        kind: "evaluate_4xx",
        status_code: 400,
        tenant_id: "acme",
        entity_id: "ent_wire_09",
        event_type: "wire_transfer",
        nats_source_subject: "fraud.events.wire_transfer",
        preview: '{"kind":"evaluate_4xx","status_code":400}',
        envelope: {
          schema_version: "1",
          kind: "evaluate_4xx",
          status_code: 400,
          nats_source_subject: "fraud.events.wire_transfer",
          event: { tenant_id: "acme", entity_id: "ent_wire_09", event_type: "wire_transfer" },
          evaluate_response_preview: '{"detail":"missing beneficiary_country"}',
        },
      },
      {
        id: "10480",
        sequence: 10480,
        subject: "fraud.events.dlq",
        received_at: null,
        kind: "invalid_json",
        status_code: null,
        tenant_id: null,
        entity_id: null,
        event_type: null,
        nats_source_subject: "fraud.events.unknown",
        preview: "{not valid json",
        envelope: {},
      },
    ];
    const items = allItems.filter((row) => {
      if (kindFilter && row.kind.toLowerCase() !== kindFilter) return false;
      if (tenantFilter && !(row.tenant_id ?? "").toLowerCase().includes(tenantFilter)) return false;
      return true;
    });
    return {
      stream_name: "FRAUD_EVENTS",
      dlq_subject: "fraud.events.dlq",
      subject_prefix: "fraud.events",
      nats_connected: true,
      jetstream_enabled: true,
      pending_estimate: 3,
      items,
      peeked_at: nowIso(),
      source: "mock",
    };
  }

  if (path.includes("/api/ingress/v1/investigation/social-engineering-monitor/config") && method === "PATCH") {
    const patchBody = (body && typeof body === "object" ? body : {}) as AnyObj;
    const tid = String(patchBody.tenant_id ?? "demo");
    if (!mockSocialEngineeringConfigByTenant[tid]) {
      mockSocialEngineeringConfigByTenant[tid] = {
        high_value_listing_usd: 5000,
        credential_change_window_minutes: 10,
      };
    }
    if (patchBody.high_value_listing_usd != null) {
      mockSocialEngineeringConfigByTenant[tid].high_value_listing_usd =
        Number(patchBody.high_value_listing_usd) || 5000;
    }
    if (patchBody.credential_change_window_minutes != null) {
      mockSocialEngineeringConfigByTenant[tid].credential_change_window_minutes = Math.max(
        1,
        Math.min(120, Number(patchBody.credential_change_window_minutes) || 10),
      );
    }
    return buildMockSocialEngineeringBoard(tid, 40, false);
  }

  if (
    path.includes("/api/ingress/v1/investigation/social-engineering-monitor") &&
    !path.includes("/config") &&
    method === "GET"
  ) {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const limit = Math.max(5, Math.min(150, Number(u.searchParams.get("limit") ?? "40") || 40));
    const onlyFlagged = u.searchParams.get("only_flagged") === "true";
    return buildMockSocialEngineeringBoard(tid, limit, onlyFlagged);
  }

  if (path.includes("/api/ingress/v1/marketplace/payout-delay") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const limit = Math.max(5, Math.min(100, Number(u.searchParams.get("limit") ?? "35") || 35));
    return buildMockPayoutDelayBoard(tid, limit);
  }

  if (path.includes("/api/ingress/v1/marketplace/payout-delay/config") && method === "PATCH") {
    let body: AnyObj = {};
    try {
      body = init?.body ? (JSON.parse(String(init.body)) as AnyObj) : {};
    } catch {
      body = {};
    }
    const tid = String(body.tenant_id ?? "demo");
    if (!mockPayoutDelayConfigByTenant[tid]) {
      mockPayoutDelayConfigByTenant[tid] = { automation_enabled: true, mule_score_hold_threshold: 72 };
    }
    if (typeof body.automation_enabled === "boolean") {
      mockPayoutDelayConfigByTenant[tid].automation_enabled = body.automation_enabled;
    }
    if (body.mule_score_hold_threshold != null) {
      mockPayoutDelayConfigByTenant[tid].mule_score_hold_threshold = Math.max(
        1,
        Math.min(99, Number(body.mule_score_hold_threshold) || 72),
      );
    }
    return buildMockPayoutDelayBoard(tid, 35);
  }

  if (
    path.includes("/api/ingress/v1/marketplace/payout-delay/") &&
    path.includes("/release") &&
    method === "POST"
  ) {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const parts = path.split("/");
    const payoutIdx = parts.indexOf("payout-delay");
    const payoutId = payoutIdx >= 0 ? decodeURIComponent(parts[payoutIdx + 1] ?? "") : "";
    mockPayoutDelayReleased.add(`${tid}:${payoutId}`);
    const board = buildMockPayoutDelayBoard(tid, 35);
    return {
      ok: true,
      release: {
        tenant_id: tid,
        payout_id: payoutId,
        released_at: nowIso(),
        released_by: "analyst",
      },
      board,
    };
  }

  if (path.includes("/api/ingress/v1/marketplace/seller-integrity") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const windowDays = Math.max(7, Math.min(90, Number(u.searchParams.get("window_days") ?? "30") || 30));
    const limit = Math.max(10, Math.min(200, Number(u.searchParams.get("limit") ?? "40") || 40));
    const profiles = [
      { deliveries: 420, reviews: 128, tier: "trusted" as const, score: 94 },
      { deliveries: 310, reviews: 98, tier: "trusted" as const, score: 91 },
      { deliveries: 95, reviews: 88, tier: "warning" as const, score: 32 },
      { deliveries: 60, reviews: 72, tier: "critical" as const, score: 18 },
      { deliveries: 0, reviews: 14, tier: "critical" as const, score: 8 },
    ];
    const sellers = Array.from({ length: limit }, (_, i) => {
      const p = profiles[i % profiles.length];
      const ratio = p.deliveries > 0 ? Math.round((p.reviews / p.deliveries) * 1000) / 1000 : p.reviews;
      const signals: string[] = [];
      if (p.deliveries === 0 && p.reviews > 0) signals.push("reviews_without_deliveries");
      if (ratio >= 1.05) signals.push("reviews_exceed_deliveries");
      else if (ratio >= 0.85) signals.push("inflated_review_to_delivery_ratio");
      return {
        seller_id: `seller_mock_${String(i).padStart(3, "0")}`,
        display_name: `Marketplace seller ${i + 1}`,
        store_slug: `store-mock-${i}`,
        category: ["electronics", "apparel", "home", "beauty", "grocery"][i % 5],
        window_days: windowDays,
        successful_deliveries: p.deliveries,
        review_count: p.reviews,
        review_to_delivery_ratio: ratio,
        integrity_score: p.score,
        integrity_tier: p.tier,
        signals,
        avg_rating: 3.5 + (i % 15) / 10,
        updated_at: new Date(Date.now() - i * 3600000).toISOString(),
      };
    });
    const atRisk = sellers.filter((s) => s.integrity_tier === "warning" || s.integrity_tier === "critical");
    const ratios = sellers.filter((s) => s.successful_deliveries > 0).map((s) => s.review_to_delivery_ratio);
    const sorted = [...ratios].sort((a, b) => a - b);
    return {
      tenant_id: tid,
      updated_at: nowIso(),
      source: "mock",
      window_days: windowDays,
      thresholds: {
        healthy_ratio_min: 0.12,
        healthy_ratio_max: 0.58,
        warn_ratio_above: 0.85,
        critical_ratio_above: 1.05,
      },
      summary: {
        seller_count: sellers.length,
        at_risk_sellers: atRisk.length,
        trusted_sellers: sellers.filter((s) => s.integrity_tier === "trusted").length,
        avg_integrity_score: Math.round(sellers.reduce((a, s) => a + s.integrity_score, 0) / sellers.length),
        median_review_to_delivery_ratio: sorted[Math.floor(sorted.length / 2)] ?? 0,
        total_deliveries: sellers.reduce((a, s) => a + s.successful_deliveries, 0),
        total_reviews: sellers.reduce((a, s) => a + s.review_count, 0),
      },
      signals:
        atRisk.length >= 3
          ? [`${atRisk.length} sellers with elevated review-to-delivery ratios`]
          : [],
      sellers: [...sellers].sort((a, b) => a.integrity_score - b.integrity_score),
    };
  }

  if (path.includes("/api/ingress/v1/investigation/synthetic-identity-detectors") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const limit = Math.max(5, Math.min(200, Number(u.searchParams.get("limit") ?? "50") || 50));
    const flagScore = Math.max(40, Math.min(95, Number(u.searchParams.get("flag_score") ?? "70") || 70));
    const ipPatterns = [
      ["low", "Residential ISP", 25],
      ["high", "Datacenter ASN", 88],
      ["high", "VPN exit node", 88],
      ["high", "Tor exit", 88],
    ] as const;
    const browserPatterns = [
      ["low", "Mainstream Chrome", 20],
      ["high", "Headless Chrome", 90],
      ["high", "Android emulator", 90],
    ] as const;
    const emailPatterns = [
      ["low", "Established domain", 15],
      ["high", "Disposable inbox", 92],
      ["high", "Plus-alias farm", 92],
    ] as const;
    const users = Array.from({ length: limit }, (_, i) => {
      const ip = ipPatterns[i % ipPatterns.length];
      const browser = browserPatterns[(i + 2) % browserPatterns.length];
      const email = emailPatterns[(i + 4) % emailPatterns.length];
      const riskScore = Math.min(
        100,
        Math.round(0.35 * ip[2] + 0.35 * browser[2] + 0.3 * email[2]),
      );
      const combo: string[] = [];
      if (ip[0] === "high" && browser[0] === "high" && email[0] === "high") {
        combo.push("synthetic_identity_triple");
      }
      if (ip[0] === "high" && email[0] === "high") combo.push("ip_email_high_risk_combo");
      const flagged = riskScore >= flagScore || combo.includes("synthetic_identity_triple");
      return {
        user_id: `syn_user_mock_${String(i).padStart(3, "0")}`,
        entity_id: `ent_syn_${String(i).padStart(4, "0")}`,
        display_name: `Signup cohort ${i + 1}`,
        email: `user${i}@maildrop.demo`,
        risk_score: riskScore,
        is_synthetic_identity: flagged,
        signals: {
          ip: { risk: ip[0], label: ip[1], detail: "Mock IP signal", score: ip[2] },
          browser: { risk: browser[0], label: browser[1], detail: "Mock browser signal", score: browser[2] },
          email: { risk: email[0], label: email[1], detail: "Mock email signal", score: email[2] },
        },
        combo_flags: combo,
        detected_at: new Date(Date.now() - i * 7200000).toISOString(),
      };
    });
    const flaggedUsers = users.filter((row) => row.is_synthetic_identity);
    return {
      tenant_id: tid,
      updated_at: nowIso(),
      source: "mock",
      thresholds: { flag_score: flagScore },
      summary: {
        scanned_users: users.length,
        flagged_users: flaggedUsers.length,
        triple_high_combos: users.filter((row) => row.combo_flags.includes("synthetic_identity_triple")).length,
        avg_risk_score: Math.round(users.reduce((s, row) => s + row.risk_score, 0) / users.length),
      },
      users: [...users].sort((a, b) => b.risk_score - a.risk_score),
    };
  }

  if (path.includes("/api/ingress/v1/ops/command-center") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    return {
      tenant_id: tid,
      updated_at: nowIso(),
      source: "mock",
      hero_kpis: [
        { id: "open_cases", label: "Cases needing review", value: 3, delta: "+1 vs yesterday", tone: "amber", route: "/cases" },
        { id: "held_payouts", label: "Payouts on hold", value: 4, delta: "$12,400 USD", tone: "violet", route: "/integrations/payout-delay" },
        { id: "syn_id", label: "Synthetic ID flags", value: 12, delta: "50 scanned", tone: "fuchsia", route: "/investigation/synthetic-identity" },
        { id: "regions_blocked", label: "Regions blacklisted", value: 3, delta: "2 critical waves", tone: "rose", route: "/compliance/regional-risk" },
      ],
      action_queue: [
        { id: "kyc-c1", title: "Send KYC ID email — c1", description: "Alice Johnson · alice@example-retail.com", route: "/cases/c1", priority: "high", module: "compliance" },
        { id: "promo", title: "Promo abuse spike — NEWUSER50", description: "47 unique redeemers", route: "/analytics/promo-abuse", priority: "elevated", module: "analytics" },
        { id: "social", title: "Social engineering bursts", description: "4 flagged accounts", route: "/investigation/social-engineering", priority: "high", module: "investigation" },
      ],
      modules: [
        { id: "cases", title: "Cases queue", route: "/cases", module: "cases", metric_label: "Open triage", metric_value: "3", tone: "amber" },
        { id: "synthetic_identity", title: "Synthetic identity", route: "/investigation/synthetic-identity", module: "investigation", metric_label: "Flagged", metric_value: "12", tone: "fuchsia" },
        { id: "promo_abuse", title: "Promo abuse", route: "/analytics/promo-abuse", module: "analytics", metric_label: "NEWUSER50", metric_value: "47", tone: "elevated" },
        { id: "review_rings", title: "Review rings", route: "/analytics/review-rings", module: "analytics", metric_label: "Clusters", metric_value: "8", tone: "cyan" },
        { id: "kyc_handover", title: "KYC handover", route: "/compliance/kyc-handover", module: "compliance", metric_label: "Pending", metric_value: "3", tone: "teal" },
        { id: "regional_risk", title: "Regional risk", route: "/compliance/regional-risk", module: "compliance", metric_label: "Blacklisted", metric_value: "3", tone: "rose" },
        { id: "payout_delay", title: "Payout delay", route: "/integrations/payout-delay", module: "integrations", metric_label: "Held", metric_value: "4", tone: "violet" },
        { id: "seller_integrity", title: "Seller integrity", route: "/integrations/seller-integrity", module: "integrations", metric_label: "At risk", metric_value: "6", tone: "amber" },
        { id: "graph", title: "Graph Explorer", route: "/graph", module: "graph", metric_label: "Risk", metric_value: "Live", tone: "normal" },
        { id: "rules", title: "Rules", route: "/rules", module: "rules", metric_label: "Policy", metric_value: "Edit", tone: "normal" },
      ],
      quick_links: [
        { label: "Live transactions", route: "/transactions/live", module: "analytics" },
        { label: "Command palette", route: "#palette", module: "dashboard", hint: "⌘K" },
        { label: "Classic dashboard", route: "/dashboard", module: "dashboard" },
        { label: "System benchmarking", route: "/ops/system-benchmarking", module: "compliance" },
      ],
    };
  }

  if (path.includes("/api/ingress/v1/compliance/regional-risk-toggles") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    return buildMockRegionalRiskBoard(tid);
  }

  if (path.includes("/api/ingress/v1/compliance/regional-risk-toggles/") && method === "PATCH") {
    const patchBody = (body && typeof body === "object" ? body : {}) as AnyObj;
    const tid = String(patchBody.tenant_id ?? "demo");
    const parts = path.split("/");
    const idx = parts.indexOf("regional-risk-toggles");
    const subRegionId = idx >= 0 ? decodeURIComponent(parts[idx + 1] ?? "") : "";
    const base = MOCK_REGIONAL_CATALOG.find((r) => r.sub_region_id === subRegionId);
    if (!base) return { ok: false, error: "sub_region_not_found" };
    if (!mockRegionalRiskBlacklist[tid]) mockRegionalRiskBlacklist[tid] = {};
    mockRegionalRiskBlacklist[tid][subRegionId] = Boolean(patchBody.blacklisted);
    const board = buildMockRegionalRiskBoard(tid);
    const sub_region = (board.sub_regions as AnyObj[]).find((r) => r.sub_region_id === subRegionId);
    return { ok: true, sub_region, board };
  }

  if (path.includes("/api/ingress/v1/compliance/kyc-handover") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const filterCase = u.searchParams.get("case_id");
    const seeds = [
      ["c1", "user_alice", "alice@example-retail.com", "Alice Johnson", 9200, true],
      ["c2", "user_bob", "bob.pending@maildrop.demo", "Bob Chen", 15000, true],
      ["c3", "user_carol", "carol.k@example.com", "Carol Okonkwo", 2400, false],
      ["c4", "fraud_frank", "frank.moretti@burner.io", "Frank Moretti", 48000, true],
      ["c5", "user_eve", "eve.m@example.com", "Eve Martinez", 11000, true],
    ] as const;
    const docs = ["government_id_front", "government_id_back", "proof_of_address"];
    const cases = seeds
      .map(([caseId, uid, email, name, amount, needsId]) => {
        const key = `${tid}:${caseId}`;
        const sent = mockKycHandoverSent[key];
        const handover = !needsId ? "not_required" : sent ? "email_sent" : "pending";
        return {
          case_id: caseId,
          tenant_id: tid,
          subject_user_id: uid,
          subject_email: email,
          display_name: name,
          case_title: `Case ${String(caseId).toUpperCase()} — $${amount.toLocaleString()} review`,
          kyc_status: needsId ? "needs_more_id" : "verified",
          documents_requested: needsId ? docs : [],
          handover_status: handover,
          email_sent_at: sent?.sent_at ?? null,
          email_message_id: sent?.message_id ?? null,
          email_template_id: sent ? "kyc_additional_id_v1" : null,
          email_subject: sent?.subject ?? null,
          amount_usd: amount,
          priority: amount >= 10000 ? "high" : "normal",
        };
      })
      .filter((c) => !filterCase || c.case_id === filterCase);
    const needs = cases.filter((c) => c.kyc_status === "needs_more_id");
    return {
      tenant_id: tid,
      updated_at: nowIso(),
      source: "mock",
      email_template_id: "kyc_additional_id_v1",
      default_documents_requested: docs,
      summary: {
        needs_more_id_count: needs.length,
        pending_email_count: needs.filter((c) => c.handover_status === "pending").length,
        email_sent_count: needs.filter((c) => c.handover_status === "email_sent").length,
      },
      cases,
    };
  }

  if (
    path.includes("/api/ingress/v1/compliance/kyc-handover/") &&
    path.includes("/send-id-email") &&
    method === "POST"
  ) {
    const patchBody = (body && typeof body === "object" ? body : {}) as AnyObj;
    const tid = String(patchBody.tenant_id ?? "demo");
    const parts = path.split("/");
    const caseIdx = parts.indexOf("kyc-handover");
    const caseId = caseIdx >= 0 ? decodeURIComponent(parts[caseIdx + 1] ?? "") : "";
    const board = getMockResponse(
      `/api/ingress/v1/compliance/kyc-handover?tenant_id=${encodeURIComponent(tid)}&case_id=${encodeURIComponent(caseId)}`,
    ) as AnyObj;
    const row = (board.cases as AnyObj[])[0];
    if (!row) return { ok: false, error: "case_not_found", case_id: caseId };
    if (row.kyc_status !== "needs_more_id") {
      return { ok: false, error: "kyc_not_pending", case_id: caseId, kyc_status: row.kyc_status };
    }
    const sentAt = nowIso();
    const messageId = `msg_mock_${caseId}_${Date.now()}`;
    const subject = "Action required: additional identity verification";
    mockKycHandoverSent[`${tid}:${caseId}`] = { sent_at: sentAt, message_id: messageId, subject };
    const handover = {
      ...row,
      handover_status: "email_sent",
      email_sent_at: sentAt,
      email_message_id: messageId,
      email_template_id: "kyc_additional_id_v1",
      email_subject: subject,
    };
    return {
      ok: true,
      case_id: caseId,
      tenant_id: tid,
      email: {
        message_id: messageId,
        sent_at: sentAt,
        to: row.subject_email,
        template_id: "kyc_additional_id_v1",
        subject,
        analyst_note: typeof patchBody.analyst_note === "string" ? patchBody.analyst_note : null,
        documents_requested: row.documents_requested,
        upload_deadline_hours: 72,
      },
      handover,
    };
  }

  if (path.includes("/api/ingress/v1/analytics/review-rings") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const minRing = Math.max(2, Math.min(15, Number(u.searchParams.get("min_ring_size") ?? "3") || 3));
    const limit = Math.max(3, Math.min(50, Number(u.searchParams.get("limit") ?? "12") || 12));
    const productTitles = [
      "Wireless noise-canceling earbuds",
      "USB-C fast charger 65W",
      "Ergonomic desk lamp",
      "Stainless steel water bottle",
      "Bluetooth mechanical keyboard",
    ];
    const clusters = Array.from({ length: limit }, (_, ci) => {
      const seed = `mock_rr_${ci}`;
      const products = productTitles.map((title, i) => ({
        product_id: `prod_${seed}_${i}`,
        title,
        category: i < 2 || i === 4 ? "electronics" : "home",
        seller_id: `seller_${seed}`,
      }));
      const memberCount = minRing + (ci % 4);
      const members = Array.from({ length: memberCount }, (_, mi) => {
        const base = Date.now() - (ci + 1) * 86400000;
        return {
          user_id: `reviewer_${seed}_${mi}`,
          display_name: `Reviewer ${mi + 1}`,
          shared_product_count: 5,
          avg_rating_given: 4.2 + (mi % 8) / 10,
          reviews: products.map((p, ri) => ({
            product_id: p.product_id,
            rating: 4 + (ri % 2),
            reviewed_at: new Date(base + ri * 3600000).toISOString(),
          })),
          first_shared_review_at: new Date(base).toISOString(),
          last_shared_review_at: new Date(base + 4 * 3600000).toISOString(),
          device_id: `dev_${seed}_${mi % 3}`,
        };
      });
      const suspicion = 45 + memberCount * 8 + (memberCount >= 5 ? 12 : 0);
      return {
        cluster_id: `rr_${seed}`,
        shared_products: products,
        shared_product_ids: products.map((p) => p.product_id),
        member_count: memberCount,
        members,
        suspicion_score: Math.min(99, suspicion),
        signals: [
          "exact_five_product_review_overlap",
          ...(memberCount >= 5 ? ["large_review_ring"] : []),
          ...(memberCount >= 4 ? ["coordinated_review_ring"] : []),
        ],
        detected_at: new Date(Date.now() - ci * 7200000).toISOString(),
      };
    }).filter((c) => c.member_count >= minRing);
    const usersInRings = clusters.reduce((s, c) => s + c.member_count, 0);
    return {
      tenant_id: tid,
      updated_at: nowIso(),
      source: "mock",
      rules: { shared_product_count: 5, min_ring_size: minRing },
      summary: {
        cluster_count: clusters.length,
        users_in_rings: usersInRings,
        high_suspicion_clusters: clusters.filter((c) => c.suspicion_score >= 70).length,
        largest_ring_size: Math.max(0, ...clusters.map((c) => c.member_count)),
      },
      signals: clusters.length
        ? [`${clusters.length} review ring(s) with identical 5-product overlap`]
        : [],
      clusters: [...clusters].sort((a, b) => b.suspicion_score - a.suspicion_score),
    };
  }

  if (path.includes("/api/ingress/v1/analytics/promo-abuse") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const code = (u.searchParams.get("coupon_code") ?? "NEWUSER50").trim().toUpperCase() || "NEWUSER50";
    const windowDays = Math.max(1, Math.min(90, Number(u.searchParams.get("window_days") ?? "7") || 7));
    const warn = 25;
    const critical = 75;
    let userCount = 47;
    if (code !== "NEWUSER50") {
      if (code === "WELCOME10" || code === "FREESHIP") userCount = 18;
      else userCount = 8 + (code.split("").reduce((a, c) => a + c.charCodeAt(0), 0) % 35);
    }
    const users = Array.from({ length: userCount }, (_, i) => {
      const deviceBucket = i % 12;
      const redemptions = i % 9 === 0 ? 2 : 1;
      const flags: string[] = [];
      if (deviceBucket < 3 && i > 5) flags.push("shared_device_cluster");
      if (redemptions > 1) flags.push("multi_redeem");
      const last = new Date(
        Date.now() - (windowDays - 1 - (i % windowDays)) * 86400000 - i * 1800000,
      ).toISOString();
      return {
        user_id: `promo_user_${code.toLowerCase()}_${String(i).padStart(4, "0")}`,
        display_name: `Marketplace user ${i + 1}`,
        redemption_count: redemptions,
        first_redeemed_at: last,
        last_redeemed_at: last,
        device_id: `dev_promo_${String(deviceBucket).padStart(2, "0")}`,
        ip_hint: `73.${deviceBucket}.${i % 256}.${(i * 7) % 256}`,
        order_total_usd: 42 + (i % 120),
        flags,
      };
    });
    const totalRedemptions = users.reduce((s, row) => s + row.redemption_count, 0);
    const devices = new Set(users.map((row) => row.device_id));
    const sharedFlags = users.filter((row) => row.flags.includes("shared_device_cluster")).length;
    const uniqueUsers = users.length;
    const risk = uniqueUsers >= critical ? "critical" : uniqueUsers >= warn ? "elevated" : "normal";
    const signals: string[] = [];
    if (uniqueUsers >= warn) {
      signals.push(
        `${uniqueUsers} unique accounts redeemed ${code} in ${windowDays}d (above ${warn} warn threshold)`,
      );
    }
    if (sharedFlags >= 5) {
      signals.push(`${sharedFlags} users map to high-overlap device clusters`);
    }
    if (totalRedemptions > uniqueUsers + 3) {
      signals.push(`${totalRedemptions - uniqueUsers} repeat redemptions beyond first-time use`);
    }
    const daily_series = Array.from({ length: windowDays }, (_, d) => {
      const date = new Date(Date.now() - (windowDays - 1 - d) * 86400000).toISOString().slice(0, 10);
      const dayUsers = users.filter((row) => row.last_redeemed_at.slice(0, 10) === date);
      return {
        date,
        unique_users: new Set(dayUsers.map((row) => row.user_id)).size,
        redemptions: dayUsers.reduce((s, row) => s + row.redemption_count, 0),
      };
    });
    return {
      tenant_id: tid,
      coupon_code: code,
      updated_at: nowIso(),
      source: "mock",
      window_days: windowDays,
      summary: {
        unique_users: uniqueUsers,
        total_redemptions: totalRedemptions,
        distinct_devices: devices.size,
        users_with_shared_device_flags: sharedFlags,
        abuse_risk: risk,
      },
      thresholds: { warn_unique_users: warn, critical_unique_users: critical },
      signals,
      daily_series,
      users: [...users].sort(
        (a, b) => b.redemption_count - a.redemption_count || a.user_id.localeCompare(b.user_id),
      ),
    };
  }

  if (path.includes("/api/ingress/v1/investigation/mule-path") && method === "GET") {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    const origin = u.searchParams.get("origin_entity_id");
    const mule = u.searchParams.get("mule_entity_id");
    const isFrank = origin === "fraud_frank" || mule === "mule_jane";
    const hops = isFrank
      ? [
          {
            role: "origin",
            entity_id: "fraud_frank",
            label: "Frank Moretti",
            node_type: "user",
            account_id: "acc_frank_burner",
            description: "Source account — funds leave here",
          },
          {
            role: "mule",
            entity_id: "mule_jane",
            label: "Jane Okafor",
            node_type: "user",
            account_id: "acc_mule_jane_recv",
            description: "Pass-through / mule account",
            referred_by: "fraud_gina",
            tags: ["mule", "layering"],
          },
          {
            role: "payout",
            entity_id: "payout_wire_offshore",
            label: "Offshore wire beneficiary",
            node_type: "payout",
            description: "Cash-out / external beneficiary",
            beneficiary: "LT71 3250 …4821",
            channel: "international_wire",
          },
        ]
      : [
          {
            role: "origin",
            entity_id: origin ?? "user_alice",
            label: "Alice Johnson",
            node_type: "user",
            account_id: "acc_alice_main",
            description: "Source account — funds leave here",
          },
          {
            role: "mule",
            entity_id: mule ?? "mule_ivan",
            label: "Ivan Kowalski",
            node_type: "user",
            account_id: "acc_mule_ivan_recv",
            description: "Pass-through / mule account",
            referred_by: "fraud_frank",
            tags: ["mule", "layering"],
          },
          {
            role: "payout",
            entity_id: "payout_crypto_eu",
            label: "External payout (crypto)",
            node_type: "payout",
            description: "Cash-out / external beneficiary",
            beneficiary: "bc1q…mule-cashout",
            channel: "crypto_withdrawal",
          },
        ];
    const leg1 = isFrank ? 8750 : 12400;
    const leg2 = isFrank ? 8500 : 11950;
    const t0 = Date.now();
    return {
      tenant_id: tid,
      path_id: `mp-${isFrank ? "fj" : "ai"}`,
      updated_at: nowIso(),
      source: "mock",
      hops,
      transfers: [
        {
          id: "xfer-1",
          from_role: "origin",
          to_role: "mule",
          from_entity_id: hops[0].entity_id,
          to_entity_id: hops[1].entity_id,
          amount: leg1,
          currency: "USD",
          trace_id: `tr-mule-${t0}`,
          timestamp: new Date(t0 - 4 * 3600_000).toISOString(),
          channel: "internal_transfer",
          status: "settled",
        },
        {
          id: "xfer-2",
          from_role: "mule",
          to_role: "payout",
          from_entity_id: hops[1].entity_id,
          to_entity_id: hops[2].entity_id,
          amount: leg2,
          currency: "USD",
          trace_id: `tr-mule-${t0 + 1}`,
          timestamp: new Date(t0 - 2 * 3600_000).toISOString(),
          channel: String(hops[2].channel ?? "payout"),
          status: "settled",
        },
      ],
      summary: {
        hop_count: 3,
        total_outflow: leg1,
        payout_amount: leg2,
        mule_retained: leg1 - leg2,
        currency: "USD",
        elapsed_hours: isFrank ? 2.8 : 4.2,
        risk_flags: ["rapid_pass_through", "mule_account", "external_payout", "known_fraud_referrer"],
      },
    };
  }

  if (path.includes("/api/ingress/v1/ops/system-benchmarking") && method === "GET") {
    const t = Date.now();
    const wave = (t / 5000) % 1;
    const w = (x: number) => Math.round(x * 1000) / 1000;
    const mk = (
      id: string,
      label: string,
      plane: string,
      base: number,
      spread: number,
      critical: boolean,
      detail: string,
    ) => {
      const samples = Array.from({ length: 7 }, (_, i) =>
        w(base + Math.sin(wave * Math.PI * 2 + i) * spread),
      );
      const sorted = [...samples].sort((a, b) => a - b);
      const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? base;
      const target = 1.0;
      const status = p95 <= target ? "on_target" : p95 <= 2 ? "near_target" : "over_target";
      return {
        id,
        label,
        plane,
        critical,
        target_ms: target,
        samples_ms: samples,
        sample_count: samples.length,
        min_ms: sorted[0],
        p50_ms: sorted[Math.floor(sorted.length / 2)],
        p95_ms: p95,
        max_ms: sorted[sorted.length - 1],
        mean_ms: w(samples.reduce((a, b) => a + b, 0) / samples.length),
        delta_p95_vs_target_ms: w(p95 - target),
        meets_sub_ms_target: p95 <= target,
        status,
        detail,
      };
    };
    const probes = [
      mk("in_process_floor", "In-process JSON + hash floor", "host", 0.04, 0.02, false, "Local CPU baseline"),
      mk("redis_ping", "Redis PING RTT", "data_plane", 0.72, 0.35, true, "redis://127.0.0.1:6379/0"),
      mk("redis_kv_roundtrip", "Redis GET/SET micro-bench", "data_plane", 1.15, 0.5, true, "One SET + GET per sample"),
      mk("rule_engine_health", "Rule engine health RTT", "decision_plane", 2.4, 0.8, true, "http://127.0.0.1:8778/health"),
      mk("decision_api_health", "Decision API health RTT", "decision_plane", 1.8, 0.6, true, "http://127.0.0.1:8001/v1/health"),
      mk(
        "integration_ingress_health",
        "Integration ingress health RTT",
        "ingress_plane",
        0.95,
        0.4,
        true,
        "http://127.0.0.1:8003/v1/health",
      ),
    ];
    const critical = probes.filter((p) => p.critical);
    const onTarget = critical.filter((p) => p.status === "on_target");
    const over = critical.filter((p) => p.status === "over_target");
    const worst = critical.reduce<(typeof probes)[0] | null>(
      (best, p) => (!best || (p.p95_ms ?? 0) > (best.p95_ms ?? 0) ? p : best),
      null,
    );
    return {
      updated_at: nowIso(),
      source: "mock",
      target: {
        name: "Sub-millisecond",
        description: "Hot-path p95 latency budget for edge data + decision planes.",
        p95_target_ms: 1.0,
        near_target_multiplier: 2.0,
      },
      methodology: {
        sample_rounds: 7,
        primary_metric: "p95_ms",
        comparison: "p95_ms <= target_ms → on target",
      },
      probes,
      summary: {
        critical_probe_count: critical.length,
        on_target_count: onTarget.length,
        over_target_count: over.length,
        all_critical_on_target: onTarget.length === critical.length,
        worst_probe_id: worst?.id ?? null,
        worst_p95_ms: worst?.p95_ms ?? null,
      },
    };
  }

  if (path.includes("/api/ingress/v1/ops/system-health-hud") && method === "GET") {
    const t = Date.now();
    const wave = (t / 4000) % 1;
    const ramPct = 58 + Math.sin(wave * Math.PI * 2) * 14;
    const redisMs = 0.6 + (Math.sin(wave * Math.PI * 2 + 1) + 1) * 2.2;
    const ollamaQ = Math.max(0, Math.min(6, Math.floor(1 + (Math.sin(wave * Math.PI * 2 + 2) + 1) * 2.5)));
    return {
      updated_at: nowIso(),
      source: "mock",
      host: {
        chip_model: "Apple M5 Pro",
        ram_total_gb: 48,
        ram_used_gb: Math.round((ramPct / 100) * 48 * 10) / 10,
        ram_used_pct: Math.round(ramPct * 10) / 10,
        memory_pressure: Math.round((ramPct / 100) * 0.85 * 1000) / 1000,
      },
      redis: {
        reachable: true,
        latency_ms: Math.round(redisMs * 100) / 100,
        endpoint_hint: "redis://127.0.0.1:6379/0",
      },
      ollama: {
        reachable: true,
        queue_depth: ollamaQ,
        model_loaded: "llama3.2:latest",
        base_url_hint: "http://127.0.0.1:11434",
      },
    };
  }

  if (path.includes("/api/ingress/v1/osint/nats-setu-monitor")) {
    const u = new URL(url, "http://localhost");
    const tid = u.searchParams.get("tenant_id") ?? "demo";
    return {
      tenant_id: tid,
      updated_at: nowIso(),
      nats_connected: true,
      jetstream_enabled: true,
      setu_query_subject: "setu.query",
      nats_url_hint: "nats://127.0.0.1:4222",
      channels: [
        {
          kind: "vpn_ip",
          label: "VPN / IP intelligence",
          status: "healthy",
          last_latency_ms: 92,
          jetstream_pending: 0,
          requests_24h: 1842,
          errors_24h: 14,
          last_error: null,
        },
        {
          kind: "email",
          label: "Email reputation",
          status: "degraded",
          last_latency_ms: 248,
          jetstream_pending: 3,
          requests_24h: 906,
          errors_24h: 118,
          last_error: "HIBP rate limit (429) — backing off 30s",
        },
        {
          kind: "phone",
          label: "Phone validation",
          status: "healthy",
          last_latency_ms: 164,
          jetstream_pending: 0,
          requests_24h: 412,
          errors_24h: 9,
          last_error: null,
        },
      ],
    };
  }
  if (path.includes("/api/ingress/v1/osint")) return { composite_risk_score: 73, risk_level: "medium", enrichments: { ip_reputation: "suspicious" }, signals_queried: 6, elapsed_ms: 42 };
  if (path.includes("/api/ingress/v1/integrations/requests/") && method === "POST") {
    const approveM = path.match(/\/integrations\/requests\/([^/]+)\/approve$/);
    if (approveM) {
      const rid = approveM[1];
      const req = mockIntegrationRequests.find((r) => r.id === rid);
      if (!req) return { ok: false, error: "not_found" };
      if (req.status !== "pending_approval") {
        if (req.status === "approved" && req.github_issue_url) {
          return { ok: true, request: req, github_issue_url: req.github_issue_url, already_approved: true };
        }
        return { ok: false, error: "not_pending" };
      }
      const approverId = String((body as AnyObj).approver_id ?? "u-admin-demo");
      const approverName = String((body as AnyObj).approver_name ?? "Demo Admin");
      req.status = "approved";
      req.approved_at = nowIso();
      req.approved_by = approverId;
      req.approved_by_name = approverName;
      const title = encodeURIComponent(`Integration request: ${req.requested_name}`);
      const issueBody = encodeURIComponent(
        `Tenant: ${req.tenant_id}\nCategory: ${req.category}\nUse case: ${req.use_case}\nGitHub user: ${req.github_username ?? ""}\nRequest ID: ${req.id}\nApproved by: ${approverName}`,
      );
      req.github_issue_url = `https://github.com/pamu512/tarka/issues/new?title=${title}&body=${issueBody}`;
      mockPlatformAudit.unshift({
        id: id("ae"),
        ts: nowIso(),
        user_id: approverId,
        user_name: approverName,
        action: "change",
        resource: `integrations:request:${rid}:approve`,
        detail: `Approved integration request — ${req.requested_name}`,
        ip: "—",
        flags: [],
      });
      return { ok: true, request: req, github_issue_url: req.github_issue_url };
    }
    const rejectM = path.match(/\/integrations\/requests\/([^/]+)\/reject$/);
    if (rejectM) {
      const rid = rejectM[1];
      const req = mockIntegrationRequests.find((r) => r.id === rid);
      if (!req) return { ok: false, error: "not_found" };
      if (req.status !== "pending_approval") return { ok: false, error: "not_pending" };
      req.status = "rejected";
      req.rejected_at = nowIso();
      req.rejected_by = "u-admin-demo";
      req.rejection_reason = String((body as AnyObj).reason ?? "");
      return { ok: true, request: req };
    }
  }
  if (path.endsWith("/api/ingress/v1/integrations/requests") && method === "GET") {
    const qi = url.indexOf("?");
    const q = qi >= 0 ? new URLSearchParams(url.slice(qi + 1)) : new URLSearchParams();
    let items = [...mockIntegrationRequests].reverse();
    const tenantId = q.get("tenant_id");
    const st = q.get("status");
    if (tenantId) items = items.filter((r) => r.tenant_id === tenantId);
    if (st) items = items.filter((r) => r.status === st);
    return { items, count: items.length };
  }
  if (path.endsWith("/api/ingress/v1/integrations/request") && method === "POST") {
    const rid = id("intreq");
    const req: AnyObj = {
      id: rid,
      tenant_id: String((body as AnyObj).tenant_id ?? "demo"),
      requested_name: String((body as AnyObj).requested_name ?? "").trim(),
      category: String((body as AnyObj).category ?? "").trim(),
      use_case: String((body as AnyObj).use_case ?? "").trim(),
      contact: String((body as AnyObj).contact ?? "").trim(),
      github_username: String((body as AnyObj).github_username ?? "").trim(),
      status: "pending_approval",
      requested_at: nowIso(),
      github_issue_url: null,
    };
    mockIntegrationRequests.unshift(req);
    return {
      ok: true,
      request: req,
      status: "pending_approval",
      github_issue_url: null,
      message:
        "Request submitted for admin review. A prefilled GitHub issue for engineering will be available after an administrator approves this request.",
    };
  }
  if (path.includes("/api/ingress/v1/integrations/catalog")) return { total_providers: 4, categories: ["crm", "device_intelligence", "ip_intelligence", "sanctions"], providers: [{ id: "ip_quality_score", name: "IPQualityScore", category: "ip_intelligence", type: "api_key", required_config_fields: ["api_key"], doc_url: "https://example.com" }, { id: "sift", name: "Sift", category: "device_intelligence", type: "api_key", required_config_fields: ["api_key"], doc_url: "https://example.com" }, { id: "jira", name: "Jira", category: "crm", type: "credentials", required_config_fields: ["username", "password"], doc_url: "https://example.com" }, { id: "opensanctions", name: "OpenSanctions", category: "sanctions", type: "api_key", required_config_fields: ["api_key"], doc_url: "https://www.opensanctions.org/docs/api/" }] };
  if (path.includes("/api/ingress/v1/integrations/installed")) return { tenant_id: "demo", installed: mockInstalledIntegrations, count: mockInstalledIntegrations.length };
  if (path.includes("/api/ingress/v1/integrations/readiness")) return { tenant_id: "demo", readiness_score: 78, covered_categories: 3, total_categories: 10, coverage: { ip_intelligence: { installed: true, count: 1 }, device_intelligence: { installed: true, count: 1 }, crm: { installed: true, count: 1 }, sanctions: { installed: false, count: 0 } } };
  if (path.includes("/api/ingress/v1/integrations/health-matrix")) return { tenant_id: "demo", score: 85, rows: mockInstalledIntegrations.map((i) => ({ provider_id: i.provider_id as string, status: "pass", latency_ms: 120, missing_fields: [] })) };
  if (path.includes("/api/ingress/v1/integrations/scorecards")) {
    const providers = mockInstalledIntegrations.map((i) => ({
      provider_id: i.provider_id as string,
      category: String(i.category ?? "crm"),
      status: "healthy",
      connectivity_score: 100,
      latency_ms: 118,
      config_completeness: 92,
      last_checked_at: nowIso(),
      reasons: [],
      provider_score: 94.2,
      connector_quality: { score: 88, version: "v1", notes: "mock" },
    }));
    const n = Math.max(providers.length, 1);
    return {
      tenant_id: "demo",
      connector_quality_version: "v1",
      overall_score: Math.round((providers.reduce((s, p) => s + p.provider_score, 0) / n) * 10) / 10,
      overall_connector_quality: Math.round((providers.reduce((s, p) => s + Number((p.connector_quality as { score?: number }).score ?? 0), 0) / n) * 10) / 10,
      providers,
    };
  }
  if (path.includes("/api/ingress/v1/integrations/install") && method === "POST") return { ok: true, integration: body };
  if (path.includes("/api/ingress/v1/integrations/uninstall") && method === "POST") return { ok: true };
  if (path.includes("/api/ingress/v1/integrations/test-connectivity")) return { provider_id: body.provider_id ?? "demo", status: "pass", latency_ms: 110, missing_fields: [], required_config_fields: [] };
  if (path.includes("/api/ingress/v1/integrations/config/")) {
    return {
      tenant_id: "demo",
      provider_id: path.split("/").pop(),
      required_config_fields: ["api_key"],
      masked_config: { api_key: "••••9abc" },
    };
  }
  if (path.includes("/api/ingress/v1/integrations/configure")) {
    return { ok: true, masked_config: { api_key: "••••9abc", password: "••••wxyz" } };
  }
  if (path.includes("/api/ingress/v1/vault/kms")) return { provider: "local", active_key_id: "kms-local-1", rotation_enabled: true, rotation_interval_seconds: 86400, config_valid: true, config_issues: [] };
  if (path.includes("/api/ingress/v1/vault/rotation-jobs")) return { jobs: [{ id: "job-1", status: "completed", old_key_id: "k1", new_key_id: "k2", processed: 150, rotated: 150, failed: 0 }] };
  if (path.includes("/api/ingress/v1/slo")) return { service: "integration-ingress", availability_target: 99.9, latency_target_ms_p95: 300, error_budget_window_days: 30, current: { kms_provider: "local", rotation_jobs: 1, rotation_failures: 0 } };

  if (path.includes("/api/cases/v1/disputes/stats")) return { total: mockDisputes.length, by_status: { open: 1 }, by_type: { chargeback: 1 }, by_outcome: {}, total_amount: 1499.99, win_rate: 0.62 };
  if (path.includes("/api/cases/v1/disputes/entity/")) return { entity_id: "fraud_frank", total_disputes: 1, fraud_confirmed_count: 1, false_positive_count: 0, total_disputed_amount: 1499.99, risk_indicator: "high", disputes: mockDisputes };
  if (path.includes("/api/cases/v1/disputes") && method === "GET") {
    const single = path.match(/\/api\/cases\/v1\/disputes\/([^/?]+)$/);
    if (single && single[1] !== "stats") {
      const found = mockDisputes.find((d) => String(d.id) === single[1]);
      return found ?? mockDisputes[0];
    }
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
      const entriesRaw = (body as AnyObj).entries;
      const entriesList = Array.isArray(entriesRaw) ? (entriesRaw as AnyObj[]) : [];
      const added = entriesList.map((e) => ({
        list_type: path.split("/").slice(-2, -1)[0],
        tenant_id: "demo",
        entity_id: e.entity_id,
        reason: e.reason ?? "",
        created_by: "ui",
        expires_at: null,
        metadata: {},
        created_at: nowIso(),
      }));
      mockListEntries = [...added, ...mockListEntries];
      return { added: added.length, entries: added };
    }
    const created = { list_type: path.split("/").pop(), tenant_id: "demo", created_at: nowIso(), ...body };
    mockListEntries = [created, ...mockListEntries];
    return created;
  }
  if (path.includes("/api/decisions/v1/lists/") && method === "DELETE") return { removed: true };

  if (path.startsWith("/api/admin/v1")) {
    const sp = new URLSearchParams(url.includes("?") ? url.split("?")[1] : "");

    if (path === "/api/admin/v1/catalog" && method === "GET") {
      return { groups: ACCESS_GROUPS };
    }
    if (path === "/api/admin/v1/overview" && method === "GET") {
      const pending = mockAdminApprovals.filter((a) => a.status === "pending").length;
      const flagged = mockPlatformAudit.filter((e) => Array.isArray(e.flags) && (e.flags as unknown[]).length > 0).length;
      return {
        active_sessions: mockAdminSessions.length,
        audit_events_flagged: flagged,
        pending_approvals: pending,
        users_configured: mockAdminUsers.length,
      };
    }
    if (path === "/api/admin/v1/sessions" && method === "GET") {
      return { items: mockAdminSessions };
    }
    if (path === "/api/admin/v1/users/access" && method === "GET") {
      return { users: mockAdminUsers };
    }
    if (path === "/api/admin/v1/audit" && method === "GET") {
      let items = [...mockPlatformAudit];
      if (sp.get("flags_only") === "1") {
        items = items.filter((e) => Array.isArray(e.flags) && (e.flags as unknown[]).length > 0);
      }
      const uid = sp.get("user_id");
      if (uid) items = items.filter((e) => e.user_id === uid);
      items.sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
      return { items };
    }
    if (path === "/api/admin/v1/approvals" && method === "GET") {
      return {
        items: [...mockAdminApprovals].sort((a, b) =>
          String(b.requested_at).localeCompare(String(a.requested_at)),
        ),
      };
    }

    const approveMatch = path.match(/^\/api\/admin\/v1\/approvals\/([^/]+)\/approve$/);
    if (approveMatch && method === "POST") {
      const apId = approveMatch[1];
      const ap = mockAdminApprovals.find((x) => x.id === apId);
      if (!ap || ap.status !== "pending") return { ok: false, error: "not_found_or_not_pending" };
      const approverId = (body.approver_id as string) ?? "u-jordan";
      const approverName = (body.approver_name as string) ?? "Jordan Lee";
      const votes = ap.votes as AnyObj[];
      if (votes.some((v) => v.user_id === approverId)) {
        return { ok: false, error: "already_voted", votes: votes.length, required: ap.required_approvals };
      }
      votes.push({ user_id: approverId, user_name: approverName, at: nowIso() });
      const required = ap.required_approvals as number;
      if (votes.length >= required) {
        ap.status = "approved";
        const u = mockAdminUsers.find((x) => x.user_id === ap.target_user_id);
        if (u) u.allowed_modules = [...(ap.proposed_allowed_modules as string[])];
        mockPlatformAudit.unshift({
          id: id("ae"),
          ts: nowIso(),
          user_id: approverId,
          user_name: approverName,
          action: "change",
          resource: "admin:access:apply",
          detail: `Dual-approved access for ${ap.target_user_name}`,
          ip: "—",
          flags: [{ type: "core_config_change", severity: "high", note: "RBAC change executed" }],
        });
      }
      return { ok: true, approval: ap, applied: votes.length >= required };
    }

    const rejectMatch = path.match(/^\/api\/admin\/v1\/approvals\/([^/]+)\/reject$/);
    if (rejectMatch && method === "POST") {
      const apId = rejectMatch[1];
      const ap = mockAdminApprovals.find((x) => x.id === apId);
      if (!ap || ap.status !== "pending") return { ok: false, error: "not_found_or_not_pending" };
      ap.status = "rejected";
      ap.rejected_at = nowIso();
      ap.rejected_by = body.approver_id ?? "u-jordan";
      return { ok: true, approval: ap };
    }

    const accessMatch = path.match(/^\/api\/admin\/v1\/users\/([^/]+)\/access$/);
    if (accessMatch && method === "PATCH") {
      const userId = accessMatch[1];
      const u = mockAdminUsers.find((x) => x.user_id === userId);
      if (!u) return { ok: false, error: "user_not_found" };
      const allowed = (body.allowed_modules as string[]) ?? [];
      const prev = new Set<string>((u.allowed_modules as string[]) ?? []);
      const next = new Set<string>(allowed);
      const check = requiresMakerChecker(prev, next);
      if (check.required) {
        const apId = id("ap");
        mockAdminApprovals.unshift({
          id: apId,
          status: "pending",
          requested_at: nowIso(),
          requested_by: (body.requested_by as string) ?? "u-admin-demo",
          requested_by_name: (body.requested_by_name as string) ?? "Demo Admin",
          summary: check.reason,
          risk_tier: check.riskTier,
          required_approvals: 2,
          target_user_id: userId,
          target_user_name: u.name,
          proposed_allowed_modules: [...next],
          previous_allowed_modules: [...prev],
          votes: [],
        });
        return {
          applied: false,
          pending_approval_id: apId,
          message: "Queued for dual approval (>1 approver required for high-risk / core).",
        };
      }
      u.allowed_modules = [...next];
      mockPlatformAudit.unshift({
        id: id("ae"),
        ts: nowIso(),
        user_id: (body.requested_by as string) ?? "u-admin-demo",
        user_name: (body.requested_by_name as string) ?? "Demo Admin",
        action: "change",
        resource: `admin:access:${userId}`,
        detail: "Module access updated (standard risk)",
        ip: "—",
        flags: [],
      });
      return { applied: true, user: u };
    }

    return { error: "admin_unknown_route", path, method };
  }

  if (path.includes("/api/investigation/v1/evidence/summary") && method === "POST") {
    const b = body as Record<string, unknown>;
    const reply = String(b.reply ?? "");
    const claims = Array.isArray(b.claims) ? (b.claims as { text?: string; source?: string }[]) : [];
    const traceId =
      typeof b.trace_id === "string"
        ? b.trace_id
        : (Array.isArray(b.source_refs)
            ? (b.source_refs as { trace_id?: string }[]).find((s) => s.trace_id)?.trace_id
            : undefined) ?? null;
    return {
      summary: reply || "No reply text in mock request.",
      confidence_label: claims.length ? ("medium" as const) : ("low" as const),
      summary_confidence: {
        level: claims.length ? "medium" : "low",
        score: claims.length ? 0.5 : 0,
        notes: ["Offline mock — connect investigation-agent for live summaries."],
      },
      claim_confidence_summary: {
        high: 0,
        medium: claims.length,
        low: 0,
      },
      citations: claims.map((c, i) => {
        const ruleId = typeof (c as { rule_id?: string }).rule_id === "string" ? (c as { rule_id: string }).rule_id : "";
        const typologyId =
          typeof (c as { typology_id?: string }).typology_id === "string" ? (c as { typology_id: string }).typology_id : "";
        const resolves: { artifact: string; id: string }[] = [];
        if (traceId) resolves.push({ artifact: "decision_trace", id: traceId });
        if (typeof b.case_id === "string" && b.case_id) resolves.push({ artifact: "case", id: b.case_id });
        if (ruleId) resolves.push({ artifact: "json_rule", id: ruleId });
        if (typologyId) resolves.push({ artifact: "typology", id: typologyId });
        return {
          claim_index: i,
          text: String(c.text ?? ""),
          source: String(c.source ?? "unknown"),
          supported: true,
          confidence_label: "medium",
          resolves_to: resolves,
        };
      }),
      next_actions: [],
      source_refs: Array.isArray(b.source_refs) ? b.source_refs : [],
      trace_id: traceId,
      case_id: typeof b.case_id === "string" ? b.case_id : null,
      turn_id: typeof b.turn_id === "string" ? b.turn_id : "mock-turn",
      prompt_version: "mock",
    };
  }

  if (path.includes("/api/investigation/v1/saarthi/feature-importance") && method === "POST") {
    const b = body as SaarthiFeatureImportanceRequestBody;
    const ranked = rankFeatureImportanceFromAudit(b);
    return { ...ranked, attribution_engine: "mock" as const };
  }

  if (path.includes("/api/investigation/v1/chat") && method === "POST") {
    return mockInvestigationChatResponse(body);
  }

  if (path.includes("/api/orchestrator/v1/analytics/transactions") && method === "GET") {
    let urlObj: URL;
    try {
      urlObj = new URL(url, "http://mock.local");
    } catch {
      urlObj = new URL("http://mock.local/");
    }
    const limit = Math.min(500, Math.max(1, Number(urlObj.searchParams.get("limit")) || 200));
    const cursorRaw = urlObj.searchParams.get("cursor") ?? "";
    let start = 0;
    try {
      const c = cursorRaw ? (JSON.parse(atob(cursorRaw)) as { o?: unknown }) : {};
      start = typeof c.o === "number" && Number.isFinite(c.o) ? Math.max(0, Math.floor(c.o)) : 0;
    } catch {
      start = 0;
    }
    const seed = buildTransactionSeed(50_000);
    const slice = seed.slice(start, start + limit);
    const rows = slice
      .map((r) =>
        mapAnalyticsTransactionRow({
          ts: r.timestamp,
          entity_id: r.entityId,
          amount: r.amountCents / 100,
          country: r.channel,
          metadata: JSON.stringify({
            trace_id: r.traceId,
            decision: r.status === "Block" ? "deny" : r.status === "Allow" ? "allow" : "review",
            channel: r.channel,
            currency: r.currency,
            ...(r.hardwareSignals ?? {}),
          }),
        }),
      )
      .filter((r): r is NonNullable<typeof r> => r != null);
    const nextStart = start + limit;
    const next_cursor = nextStart < seed.length ? btoa(JSON.stringify({ o: nextStart })) : null;
    return {
      rows,
      next_cursor,
      query_ms: 3.8 + (limit % 7) * 0.4,
      backend: "duckdb",
    };
  }

  return null;
}
