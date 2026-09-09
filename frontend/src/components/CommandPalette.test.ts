import { describe, expect, it } from "vitest";

import { MODULE_ROUTES_ALL } from "./CommandPalette";

describe("CommandPalette module routes", () => {
  it("lists the visual rule builder next to /rules", () => {
    expect(MODULE_ROUTES_ALL.some((r) => r.to === "/rules/visual")).toBe(true);
    const visual = MODULE_ROUTES_ALL.find((r) => r.to === "/rules/visual");
    expect(visual?.label.toLowerCase()).toMatch(/not a product sku/i);
    expect(MODULE_ROUTES_ALL.some((r) => r.to === "/ops/shadow" && /sentence pack/i.test(r.label))).toBe(true);
  });
});
