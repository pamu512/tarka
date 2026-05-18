import { describe, expect, it } from "vitest";

import { formatPotentialSavings, sumBlockedAmounts } from "./potentialSavings";

describe("potentialSavings", () => {
  it("sums blocked amounts", () => {
    expect(sumBlockedAmounts([100, 250.5, -1, NaN])).toBe(350.5);
  });

  it("formats currency for impact display", () => {
    const s = formatPotentialSavings(125_000, "USD", "en-US");
    expect(s).toContain("125");
  });
});
