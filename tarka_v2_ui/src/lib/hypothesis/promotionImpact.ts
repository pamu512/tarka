import type { BacktestBlockPoint } from "./backtestBlockSeries";

export type PromotionSummaryInput = {
  ruleLabel: string;
  estimatedBlockRateImpactPct: number | null;
};

/** Display id such as ``#902`` from rule JSON or metadata. */
export function formatRuleLabel(
  rule: Record<string, unknown> | null | undefined,
  fallback = "#—",
): string {
  if (!rule || typeof rule !== "object") return fallback;
  const meta = rule.metadata;
  if (meta && typeof meta === "object") {
    const m = meta as Record<string, unknown>;
    const num = m.rule_number ?? m.display_id;
    if (typeof num === "number" && Number.isFinite(num)) {
      return `#${num}`;
    }
    if (typeof num === "string" && num.trim()) {
      return num.trim().startsWith("#") ? num.trim() : `#${num.trim()}`;
    }
  }
  const id = String(rule.id ?? "").trim();
  const tail = id.match(/_(\d{2,})$/)?.[1] ?? id.match(/(\d{3,})$/)?.[1];
  if (tail) return `#${tail}`;
  if (id) return id.startsWith("#") ? id : `#${id}`;
  return fallback;
}

/**
 * Estimated uplift in block rate vs production-only blocks over the backtest window.
 * Uses aggregate shadow vs production block counts from the visualizer series.
 */
export function estimateBlockRateImpactPct(
  backtestBlockSeries: readonly BacktestBlockPoint[] | null | undefined,
  overridePct?: number | null,
): number | null {
  if (overridePct != null && Number.isFinite(overridePct)) {
    return Math.round(overridePct * 10) / 10;
  }
  if (!backtestBlockSeries?.length) return null;
  const productionTotal = backtestBlockSeries.reduce((s, r) => s + r.production_blocks, 0);
  const shadowTotal = backtestBlockSeries.reduce((s, r) => s + r.shadow_blocks, 0);
  if (shadowTotal <= 0) return null;
  if (productionTotal <= 0) {
    return Math.min(100, Math.round(shadowTotal * 1.5 * 10) / 10);
  }
  const uplift = ((shadowTotal - productionTotal) / productionTotal) * 100;
  return Math.round(uplift * 10) / 10;
}

export function buildPromotionSummaryText(input: PromotionSummaryInput): string {
  const impact =
    input.estimatedBlockRateImpactPct != null
      ? `+${input.estimatedBlockRateImpactPct}%`
      : "an unquantified";
  return `This will transition Rule ${input.ruleLabel} from Observation to Active. Estimated impact: ${impact} block rate.`;
}

export function ruleForProductionDeploy(
  rule: Record<string, unknown>,
): Record<string, unknown> {
  const meta =
    rule.metadata && typeof rule.metadata === "object"
      ? { ...(rule.metadata as Record<string, unknown>) }
      : {};
  delete meta.is_shadow;
  meta.promoted_from = "observation";
  meta.mode = "active";
  return {
    ...rule,
    metadata: meta,
  };
}
