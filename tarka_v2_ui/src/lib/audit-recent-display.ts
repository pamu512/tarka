import type { AuditRecentItem, AuditRuleResult } from "@/types/audit-recent";

export type AuditRecentDisplayRow = {
  transaction_id: string;
  short_id: string;
  amount_cents: number;
  rule_result: AuditRuleResult;
  ai_confidence: number | null;
};

export function deriveShortId(transactionId: string): string {
  const compact = transactionId.replace(/[^a-fA-F0-9]/g, "");
  if (compact.length >= 8) return compact.slice(0, 8).toUpperCase();
  return transactionId.replace(/[^a-zA-Z0-9]/g, "").slice(0, 8).toUpperCase().padEnd(8, "0");
}

/** Deterministic fallback confidence when the API omits ``ai_confidence``. */
export function syntheticConfidence(
  ruleResult: AuditRuleResult,
  transactionId: string,
): number | null {
  if (ruleResult === "BLOCK" || ruleResult === "ALLOW") return null;
  let h = 0;
  for (let i = 0; i < transactionId.length; i++) {
    h = (h * 31 + transactionId.charCodeAt(i)) >>> 0;
  }
  return Math.min(0.99, 0.42 + (h % 53) / 100);
}

export function toDisplayRow(item: AuditRecentItem): AuditRecentDisplayRow {
  const rule_result = item.rule_result ?? item.status;
  return {
    transaction_id: item.transaction_id,
    short_id: item.short_id ?? deriveShortId(item.transaction_id),
    amount_cents: item.amount_cents,
    rule_result,
    ai_confidence:
      item.ai_confidence !== undefined
        ? item.ai_confidence
        : syntheticConfidence(rule_result, item.transaction_id),
  };
}

export function formatAmountCents(cents: number): string {
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const formatted = (abs / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return negative ? `−$${formatted}` : `$${formatted}`;
}

export function formatConfidence(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%`;
}

export function ruleResultTone(rr: AuditRuleResult): string {
  switch (rr) {
    case "ALLOW":
      return "text-emerald-400";
    case "BLOCK":
      return "text-red-400";
    case "SHADOW_REVIEW":
      return "text-violet-300";
    default:
      return "text-amber-300";
  }
}
