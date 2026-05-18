import { buildBaseMockItems } from "@/lib/mock-audit-items";
import type { AuditRecentItem } from "@/types/audit-recent";

/**
 * In-memory attack outcomes prepended to the synthetic feed (dev/mock API only).
 * Keeps GET /v1/audit/recent aligned with streamed POST /v1/demo/simulate_attack.
 */
const attackOutcomes: AuditRecentItem[] = [];

const MAX_ATTACK_BUFFER = 40;
const MAX_RETURN = 50;

export function pushAttackOutcome(item: AuditRecentItem): void {
  attackOutcomes.unshift(item);
  if (attackOutcomes.length > MAX_ATTACK_BUFFER) {
    attackOutcomes.length = MAX_ATTACK_BUFFER;
  }
}

export function getMergedRecentItems(nowMs: number): AuditRecentItem[] {
  const base = buildBaseMockItems(nowMs);
  const seen = new Set<string>();
  const merged: AuditRecentItem[] = [];

  for (const row of [...attackOutcomes, ...base]) {
    if (seen.has(row.transaction_id)) continue;
    seen.add(row.transaction_id);
    merged.push(row);
    if (merged.length >= MAX_RETURN) break;
  }

  return merged;
}
