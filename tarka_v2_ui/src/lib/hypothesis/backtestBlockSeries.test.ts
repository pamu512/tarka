import { describe, expect, it } from "vitest";

import { normalizeBacktestBlockSeries, totalShadowOnlyBlocks } from "./backtestBlockSeries";

describe("backtestBlockSeries", () => {
  it("normalizes backend rows and computes shadow-only total", () => {
    const series = normalizeBacktestBlockSeries([
      {
        bucket: "2026-05-18 10:00:00",
        production_blocks: 2,
        shadow_blocks: 8,
        shadow_only_blocks: 6,
      },
      {
        bucket: "2026-05-18 11:00:00",
        production_blocks: 1,
        shadow_blocks: 12,
        shadow_only_blocks: 11,
      },
    ]);
    expect(series).toHaveLength(2);
    expect(series[0]?.label.length).toBeGreaterThan(0);
    expect(totalShadowOnlyBlocks(series)).toBe(17);
  });
});
