/**
 * Canonical transaction envelope evaluated by the rule engine (raw schema).
 */
export type TransactionSchema = {
  schema_version: string;
  transaction_id: string;
  amount_cents: number;
  currency: string;
  channel: "card_not_present" | "card_present" | "ach" | "wire";
  merchant_id: string;
  instrument_fingerprint: string;
  ip_asn: string;
  geo_country: string;
  mcc: string;
  velocity_window_minutes: number;
  prior_declines_24h: number;
  metadata: Record<string, string | number | boolean>;
};

/**
 * Shadow model output mirrored alongside engine decisions.
 */
export type ShadowDecision = {
  model_id: string;
  shadow_verdict: string;
  confidence: number;
  risk_tags: string[];
  /** Ordered reasoning steps — strings and/or structured objects. */
  ai_reasoning: unknown;
  latency_ms: number;
  counterfactuals_considered: number;
};

export type DecisionDetailResponse = {
  transaction_schema: TransactionSchema;
  shadow_decision: ShadowDecision;
};
