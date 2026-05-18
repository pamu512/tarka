import { describe, expect, it } from "vitest";

import { isSyntheticIdentityFlagged, SYNTHETIC_IDENTITY_FLAG_SCORE } from "./syntheticIdentity";

describe("isSyntheticIdentityFlagged", () => {
  it("flags at threshold", () => {
    expect(isSyntheticIdentityFlagged(SYNTHETIC_IDENTITY_FLAG_SCORE)).toBe(true);
    expect(isSyntheticIdentityFlagged(SYNTHETIC_IDENTITY_FLAG_SCORE - 1)).toBe(false);
  });

  it("respects explicit boolean", () => {
    expect(isSyntheticIdentityFlagged(10, true)).toBe(true);
    expect(isSyntheticIdentityFlagged(99, false)).toBe(false);
  });
});
