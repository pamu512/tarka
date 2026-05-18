export type AuditRecentStatus =
  | "BLOCK"
  | "FLAG"
  | "SHADOW_REVIEW"
  | "ALLOW";

/** Alias for audit-first column headers (same wire values as ``status``). */
export type AuditRuleResult = AuditRecentStatus;

export type AuditRecentItem = {
  timestamp: string;
  transaction_id: string;
  amount_cents: number;
  status: AuditRecentStatus;
  /** First 8 hex chars of entity id when API omits this field. */
  short_id?: string;
  rule_result?: AuditRuleResult;
  /** Model confidence 0–1; null when deterministic-only path. */
  ai_confidence?: number | null;
};

export type AuditRecentResponse = {
  items: AuditRecentItem[];
};
