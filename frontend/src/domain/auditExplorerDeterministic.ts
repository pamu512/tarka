import type { AuditRecentItem, AuditRuleResult } from "../api/client";

const RULE_CYCLE: readonly AuditRuleResult[] = ["ALLOW", "DENY", "REVIEW", "SHADOW_REVIEW"];

/** Stable epoch so pagination requests return identical rows for the same offset across refreshes. */
const SYNTHETIC_EPOCH_MS = 1704067200000;

/**
 * Deterministic synthetic audit row — used by dev mocks and stress demos without storing rows.
 * Real services should return persisted audit projections instead.
 */
export function deterministicAuditRecentItem(offset: number): AuditRecentItem {
  const trace_id = `a${offset.toString(16).padStart(7, "0")}-b00${offset % 1000}-4000-8000-${((offset * 7919) >>> 0).toString(16).padStart(12, "0")}`;
  const hex = trace_id.replace(/-/g, "");
  const short_id = hex.slice(0, 8).toUpperCase();
  const rr = RULE_CYCLE[Math.abs(offset) % RULE_CYCLE.length]!;
  const created_at = new Date(SYNTHETIC_EPOCH_MS - offset * 1300).toISOString();
  return {
    trace_id,
    short_id,
    amount: Math.round((12.5 + offset * 3.17 + (offset % 97)) * 100) / 100,
    currency: "USD",
    rule_result: rr,
    ai_confidence: Math.min(0.99, 0.35 + (Math.abs(offset * 17) % 60) / 100),
    created_at,
  };
}
