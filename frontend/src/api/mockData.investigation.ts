import {
  rankFeatureImportanceFromAudit,
  type SaarthiFeatureImportanceRequestBody,
} from "../lib/saarthi/featureImportance";
import { isSessionNoiseAuditRow } from "../utils/copilotContext";
import { type AnyObj, mockRandomAlpha } from "./mockData.shared";

export type InvestigationMockDeps = {
  mockPlatformAudit: AnyObj[];
};

export type InvestigationMockRequest = {
  url: string;
  path: string;
  method: string;
  body: AnyObj;
};

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
  deps: InvestigationMockDeps,
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
      : [...deps.mockPlatformAudit].sort((a, b) => String(b.ts).localeCompare(String(a.ts))).slice(0, 20);

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
function mockInvestigationChatResponse(body: AnyObj, deps: InvestigationMockDeps): AnyObj {
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
      deps,
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
      deps,
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
      deps,
    );
  }
  if (t.includes("a/b") || t.includes("ab test") || t.includes("shadow") || t.includes("experiment")) {
    return finalizeInvestigationMockReply(
      "**Experiment readout (mock)** — Hold segment mix constant. Primary: review rate & estimated $ at risk; guardrail: deny false-positive proxy. Run at least one full weekly cycle before promote; pre-define rollback if review queue >15% over baseline.",
      [toolAudit],
      body,
      deps,
    );
  }
  if (t.includes("report") || t.includes("monitoring") || t.includes("weekly") || t.includes("digest")) {
    return finalizeInvestigationMockReply(
      "**Monitoring report skeleton (mock)** — (1) Volume & decision mix (2) SLA / aging (3) Top entities (4) Rule leaders (5) Graph rings called out (6) Experiments (7) Action items. Replace date placeholders before sharing.",
      [],
      body,
      deps,
    );
  }
  if (t.includes("rule") && (t.includes("gap") || t.includes("improve") || t.includes("opa"))) {
    return finalizeInvestigationMockReply(
      "**Rule-base ideas (mock, advisory)** — Tighten velocity windows for high-risk channels; add list cross-check for devices seen on >3 entities in 24h; tag VPN + emulator combo for manual review. Validate via replay before production.",
      [toolAudit, toolGraph],
      body,
      deps,
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
      deps,
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
    deps,
  );
}

/** Dispatch ``/api/investigation/v1/*`` mock routes; returns ``null`` when path is not handled. */
export function getInvestigationMockResponse(
  req: InvestigationMockRequest,
  deps: InvestigationMockDeps,
): unknown | null {
  const { url, path, method, body } = req;

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
      title: String(body.title ?? "untitled").slice(0, 256),
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
    return mockInvestigationChatResponse(body, deps);
  }

  return null;
}
