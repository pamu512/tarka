import type {
  DecisionDetailResponse,
  ShadowDecision,
  TransactionSchema,
} from "@/types/decision-detail";

const CHANNELS = new Set<TransactionSchema["channel"]>([
  "card_not_present",
  "card_present",
  "ach",
  "wire",
]);

function asRecord(raw: unknown): Record<string, unknown> | null {
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : null;
}

function asString(raw: unknown, fallback = ""): string {
  return typeof raw === "string" ? raw : fallback;
}

function asNumber(raw: unknown, fallback = 0): number {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

function asStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((x): x is string => typeof x === "string" && x.trim().length > 0);
}

function normalizeMetadata(raw: unknown): Record<string, string | number | boolean> {
  const o = asRecord(raw);
  if (!o) return {};
  const out: Record<string, string | number | boolean> = {};
  for (const [k, v] of Object.entries(o)) {
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      out[k] = v;
    }
  }
  return out;
}

function normalizeChannel(raw: unknown): TransactionSchema["channel"] {
  const s = asString(raw, "card_not_present");
  return CHANNELS.has(s as TransactionSchema["channel"])
    ? (s as TransactionSchema["channel"])
    : "card_not_present";
}

function normalizeTransactionSchema(raw: unknown): TransactionSchema | null {
  const o = asRecord(raw);
  if (!o) return null;
  const transactionId = asString(o.transaction_id);
  if (!transactionId) return null;
  return {
    schema_version: asString(o.schema_version, "v2.1"),
    transaction_id: transactionId,
    amount_cents: Math.max(0, Math.round(asNumber(o.amount_cents))),
    currency: asString(o.currency, "USD").slice(0, 8) || "USD",
    channel: normalizeChannel(o.channel),
    merchant_id: asString(o.merchant_id, "unknown"),
    instrument_fingerprint: asString(o.instrument_fingerprint, "unknown"),
    ip_asn: asString(o.ip_asn, "unknown"),
    geo_country: asString(o.geo_country, "ZZ").slice(0, 8) || "ZZ",
    mcc: asString(o.mcc, "0000"),
    velocity_window_minutes: Math.max(0, Math.round(asNumber(o.velocity_window_minutes, 15))),
    prior_declines_24h: Math.max(0, Math.round(asNumber(o.prior_declines_24h))),
    metadata: normalizeMetadata(o.metadata),
  };
}

function normalizeShadowDecision(raw: unknown): ShadowDecision | null {
  const o = asRecord(raw);
  if (!o) return null;
  const modelId = asString(o.model_id);
  const verdict = asString(o.shadow_verdict);
  if (!modelId || !verdict) return null;
  const confidence = asNumber(o.confidence);
  return {
    model_id: modelId,
    shadow_verdict: verdict,
    confidence: Math.min(1, Math.max(0, confidence > 1 ? confidence / 100 : confidence)),
    risk_tags: asStringArray(o.risk_tags),
    ai_reasoning: "ai_reasoning" in o ? o.ai_reasoning : null,
    latency_ms: Math.max(0, Math.round(asNumber(o.latency_ms))),
    counterfactuals_considered: Math.max(0, Math.round(asNumber(o.counterfactuals_considered))),
  };
}

/**
 * Validates orchestrator ``GET /v1/decisions/{id}`` payloads for ``DecisionDetail``.
 */
export function normalizeDecisionDetailResponse(raw: unknown): DecisionDetailResponse | null {
  const o = asRecord(raw);
  if (!o) return null;
  const transaction_schema = normalizeTransactionSchema(o.transaction_schema);
  const shadow_decision = normalizeShadowDecision(o.shadow_decision);
  if (!transaction_schema || !shadow_decision) return null;
  const out: DecisionDetailResponse = { transaction_schema, shadow_decision };
  if ("evaluation_trace" in o) {
    out.evaluation_trace = o.evaluation_trace;
  }
  return out;
}
