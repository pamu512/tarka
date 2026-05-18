import { deriveShortId, syntheticConfidence } from "@/lib/audit-recent-display";
import type { AuditRecentItem, AuditRecentStatus } from "@/types/audit-recent";

const STATUSES: readonly AuditRecentStatus[] = [
  "BLOCK",
  "FLAG",
  "SHADOW_REVIEW",
  "ALLOW",
] as const;

/** Rolling synthetic feed used as the tail of the merged recent list. */
export function buildBaseMockItems(nowMs: number): AuditRecentItem[] {
  const tick = Math.floor(nowMs / 2000);

  return Array.from({ length: 20 }, (_, i) => {
    const offsetMs = i * 1731 + (tick % 7) * 113;
    const ts = new Date(nowMs - offsetMs).toISOString();
    const status = STATUSES[(i + tick) % STATUSES.length];
    const suffix = ((nowMs + i * 997) % 1_000_000).toString(36).padStart(5, "0");
    const transaction_id = `txn_${(nowMs - offsetMs).toString(36)}_${suffix}_audit`;

    return {
      timestamp: ts,
      transaction_id,
      amount_cents: Math.round((Math.sin(tick + i) * 0.5 + 0.5) * 250_000) - 5000,
      status,
      short_id: deriveShortId(transaction_id),
      rule_result: status,
      ai_confidence: syntheticConfidence(status, transaction_id),
    };
  });
}
