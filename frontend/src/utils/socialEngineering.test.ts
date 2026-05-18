import { describe, expect, it } from "vitest";

import { isSocialEngineeringFlagged } from "./socialEngineering";

describe("isSocialEngineeringFlagged", () => {
  it("flags explicit boolean", () => {
    expect(isSocialEngineeringFlagged(true)).toBe(true);
    expect(isSocialEngineeringFlagged(false)).toBe(false);
  });

  it("flags burst signal", () => {
    expect(isSocialEngineeringFlagged(false, ["social_engineering_credential_burst"])).toBe(true);
  });
});
