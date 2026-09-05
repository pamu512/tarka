import { describe, expect, it } from "vitest";

import { showFirstHourHint } from "./FirstHourHint";

describe("showFirstHourHint", () => {
  it("shows for demo tenant even when not in dev", () => {
    expect(showFirstHourHint("demo", { isDev: false })).toBe(true);
  });

  it("hides for other tenants outside dev", () => {
    expect(showFirstHourHint("acme", { isDev: false })).toBe(false);
  });
});
