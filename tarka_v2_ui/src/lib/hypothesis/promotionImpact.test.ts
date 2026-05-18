import { describe, it, expect } from "vitest";

import {
  buildPromotionSummaryText,
  estimateBlockRateImpactPct,
  formatRuleLabel,
  ruleForProductionDeploy,
} from "./promotionImpact";
import type { BacktestBlockPoint } from "./backtestBlockSeries";

describe("promotionImpact", () => {
  it("gate 199: formats rule label and final promotion summary", () => {
    const rule = {
      id: "shadow_rule_902",
      metadata: { rule_number: 902, is_shadow: true, mode: "observation" },
    };
    expect(formatRuleLabel(rule)).toBe("#902");
    const summary = buildPromotionSummaryText({
      ruleLabel: "#902",
      estimatedBlockRateImpactPct: 15,
    });
    expect(summary).toBe(
      "This will transition Rule #902 from Observation to Active. Estimated impact: +15% block rate.",
    );
  });

  it("estimates block-rate uplift from backtest series", () => {
    const series: BacktestBlockPoint[] = [
      {
        bucket: "2026-01-01T00:00:00Z",
        label: "Jan 1",
        production_blocks: 100,
        shadow_blocks: 115,
        shadow_only_blocks: 15,
      },
      {
        bucket: "2026-01-01T01:00:00Z",
        label: "Jan 1",
        production_blocks: 100,
        shadow_blocks: 115,
        shadow_only_blocks: 15,
      },
    ];
    expect(estimateBlockRateImpactPct(series)).toBe(15);
    expect(estimateBlockRateImpactPct(series, 12.3)).toBe(12.3);
  });

  it("strips shadow metadata for production deploy", () => {
    const out = ruleForProductionDeploy({
      id: "r1",
      metadata: { is_shadow: true, mode: "observation" },
    });
    const meta = out.metadata as Record<string, unknown>;
    expect(meta.is_shadow).toBeUndefined();
    expect(meta.mode).toBe("active");
    expect(meta.promoted_from).toBe("observation");
  });
});
