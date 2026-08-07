/**
 * Disputes mock slice — shrink of mockData.ts for `/api/cases/v1/disputes*`.
 */

import { type AnyObj, mockRandomAlpha } from "./mockData.shared";

const nowIso = () => new Date().toISOString();
const id = (prefix: string) => `${prefix}-${mockRandomAlpha(8)}`;

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

export function getDisputesMockResponse(args: {
  url: string;
  path: string;
  method: string;
  body: Record<string, unknown>;
}): unknown | null {
  const { path, method, body } = args;

  if (!path.includes("/api/cases/v1/disputes")) {
    return null;
  }

  if (path.includes("/api/cases/v1/disputes/ops/deadline-queue")) {
    const now = Date.now();
    const filed = new Date(now - 8 * 3600 * 1000).toISOString();
    const deadlineNear = new Date(now + 45 * 60 * 1000).toISOString();
    const deadlineBreached = new Date(now - 30 * 60 * 1000).toISOString();
    return {
      schema: "tarka.dispute_deadline_queue/v1",
      tenant_id: "demo",
      generated_at: new Date(now).toISOString(),
      items: [
        {
          dispute_id: "d1",
          tenant_id: "demo",
          status: "filed",
          dispute_type: "chargeback",
          filed_at: filed,
          provider_response_deadline_at: deadlineBreached,
          seconds_remaining: 0,
          alert_state: "breached",
          suggested_alert_hooks: ["POST /v1/disputes/{dispute_id}/reprocess-external?tenant_id=..."],
          external_reprocess_count: 1,
          last_external_reprocess_at: null,
        },
        {
          dispute_id: "d2",
          tenant_id: "demo",
          status: "investigating",
          dispute_type: "chargeback",
          filed_at: filed,
          provider_response_deadline_at: deadlineNear,
          seconds_remaining: 45 * 60,
          alert_state: "near_breach",
          suggested_alert_hooks: ["POST /v1/disputes/{dispute_id}/reprocess-external?tenant_id=..."],
          external_reprocess_count: 0,
          last_external_reprocess_at: null,
        },
        {
          dispute_id: "d3",
          tenant_id: "demo",
          status: "evidence_submitted",
          dispute_type: "chargeback",
          filed_at: filed,
          provider_response_deadline_at: new Date(now + 48 * 3600 * 1000).toISOString(),
          seconds_remaining: 48 * 3600,
          alert_state: "ok",
          suggested_alert_hooks: [],
          external_reprocess_count: 0,
          last_external_reprocess_at: null,
        },
      ],
    };
  }
  if (path.match(/\/api\/cases\/v1\/disputes\/[^/]+\/reprocess-external$/)) {
    return {
      ok: true,
      dispute_id: "d1",
      tenant_id: "demo",
      reprocessed_at: nowIso(),
      external_reprocess_count: 2,
      reason: String(body.reason ?? ""),
      idempotent_replay: false,
    };
  }
  if (path.includes("/api/cases/v1/disputes/stats")) {
    return {
      total: mockDisputes.length,
      by_status: { open: 1 },
      by_type: { chargeback: 1 },
      by_outcome: {},
      total_amount: 1499.99,
      win_rate: 0.62,
    };
  }
  if (path.includes("/api/cases/v1/disputes/entity/")) {
    return {
      entity_id: "fraud_frank",
      total_disputes: 1,
      fraud_confirmed_count: 1,
      false_positive_count: 0,
      total_disputed_amount: 1499.99,
      risk_indicator: "high",
      disputes: mockDisputes,
    };
  }
  if (method === "GET") {
    const single = path.match(/\/api\/cases\/v1\/disputes\/([^/?]+)$/);
    if (single && single[1] !== "stats") {
      const found = mockDisputes.find((d) => String(d.id) === single[1]);
      return found ?? mockDisputes[0];
    }
    return { items: mockDisputes };
  }
  if (method === "POST") {
    const d = { id: id("d"), status: "open", created_at: nowIso(), updated_at: nowIso(), ...body };
    mockDisputes = [d, ...mockDisputes];
    return d;
  }
  if (method === "PATCH") {
    return { ...mockDisputes[0], ...body, updated_at: nowIso() };
  }

  return null;
}
