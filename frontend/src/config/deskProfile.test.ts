import { describe, expect, it } from "vitest";
import { resolveDeskProfile } from "./deskProfile";

describe("resolveDeskProfile", () => {
  it("prefers VITE_DESK_PROFILE over VITE_LEAN_NAV", () => {
    expect(resolveDeskProfile({ profile: "product", leanNav: "false" })).toBe("product");
    expect(resolveDeskProfile({ profile: "demo", leanNav: "false" })).toBe("demo");
    expect(resolveDeskProfile({ profile: "brochure", leanNav: "true" })).toBe("brochure");
  });

  it("maps legacy VITE_LEAN_NAV when profile is unset", () => {
    expect(resolveDeskProfile({ leanNav: "false" })).toBe("brochure");
    expect(resolveDeskProfile({ leanNav: "true" })).toBe("demo");
    expect(resolveDeskProfile({})).toBe("demo");
  });

  it("treats unknown profile as demo", () => {
    expect(resolveDeskProfile({ profile: "enterprise" })).toBe("demo");
  });
});
