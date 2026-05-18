import { describe, expect, it } from "vitest";
import { parseCaseDetailRoute } from "./caseOpenQuery";

describe("parseCaseDetailRoute", () => {
  it("excludes tool routes from case detail matching", () => {
    expect(parseCaseDetailRoute("/cases/bulk-triage")).toBeNull();
    expect(parseCaseDetailRoute("/cases/compare")).toBeNull();
  });

  it("still parses a normal case id", () => {
    expect(parseCaseDetailRoute("/cases/c1")).toEqual({ caseId: "c1" });
  });
});
