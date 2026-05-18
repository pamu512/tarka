import { describe, expect, it } from "vitest";

import { maskPiiValue } from "./maskPii";

describe("maskPiiValue", () => {
  it("masks email local part", () => {
    expect(maskPiiValue("alex.chen@demo.tarka", "email")).toBe("al***@demo.tarka");
  });

  it("masks phone tail", () => {
    expect(maskPiiValue("+1 415 555 0199", "phone")).toBe("***0199");
  });

  it("masks financial tail", () => {
    expect(maskPiiValue("4111111111111111", "financial")).toBe("****1111");
  });
});
