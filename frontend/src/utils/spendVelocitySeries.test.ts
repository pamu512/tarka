import { describe, expect, it } from "vitest";

import { allocateSpendByHour } from "./spendVelocitySeries";

describe("allocateSpendByHour", () => {
  it("splits total spend in proportion to buckets", () => {
    const b = Array(24).fill(0);
    b[10] = 10;
    b[11] = 10;
    const out = allocateSpendByHour(b, 100);
    expect(out[10] + out[11]).toBeCloseTo(100, 5);
    expect(out[10]).toBeCloseTo(50, 5);
  });

  it("returns zeros when buckets empty", () => {
    expect(allocateSpendByHour(Array(24).fill(0), 50).every((x) => x === 0)).toBe(true);
  });
});
