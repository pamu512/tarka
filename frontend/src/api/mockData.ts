import { ACCESS_GROUPS, requiresMakerChecker } from "../config/accessModuleCatalog";
import { isSessionNoiseAuditRow } from "../utils/copilotContext";

type AnyObj = Record<string, unknown>;

const nowIso = () => new Date().toISOString();

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

/** Pending / approved integration requests (GitHub ticket only after admin approve). */
let mockIntegrationRequests: AnyObj[] = [];

let mockAdminUsers: AnyObj[] = [
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

let mockAdminSessions: AnyObj[] = [
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

let mockPlatformAudit: AnyObj[] = [
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

let mockAdminApprovals: AnyObj[] = [
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
    const intents = ensureMockSarIntents(caseId);
    const intent = intents.find((x) => x.id === intentId) as AnyObj | undefined;
    if (!intent) return { sar_filing_intent_id: intentId, status: "PENDING_REVIEW" };
    if (intent.status === "APPROVED") return { sar_filing_intent_id: intentId, status: "APPROVED" };
    if (intent.status === "PENDING_REVIEW") {
      const ts = nowIso();
      intent.status = "APPROVED";
      intent.updated_at = ts;
      const log = intent.audit_log as AnyObj[];
      log.push({
        id: id("aud"),
        from_status: "PENDING_REVIEW",
        to_status: "APPROVED",
        actor: "analyst",
        detail: { reason_code: "SAR_APPROVED" },
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
    if (intent.status === "APPROVED") {
      const ts = nowIso();
      intent.status = "SFTP_QUEUED";
      intent.updated_at = ts;
      const log = intent.audit_log as AnyObj[];
      log.push({
        id: id("aud"),
        from_status: "APPROVED",
        to_status: "SFTP_QUEUED",
        actor: "analyst",
        detail: { reason_code: "SAR_SFTP_QUEUED" },
        stack_trace: null,
        created_at: ts,
      });
    }
    return { sar_filing_intent_id: intentId, status: intent.status };
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
  if (path.includes("/api/ingress/v1/integrations/config/")) return { tenant_id: "demo", provider_id: path.split("/").pop(), required_config_fields: ["api_key"], masked_config: { api_key: "****demo" } };
  if (path.includes("/api/ingress/v1/integrations/configure")) return { ok: true, masked_config: { api_key: "****demo" } };
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

  if (path.includes("/api/investigation/v1/chat") && method === "POST") {
    return mockInvestigationChatResponse(body);
  }

  return null;
}
