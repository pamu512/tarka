import { describe, expect, it } from "vitest";

import { buildCaseComparisonHref } from "./caseComparisonUrl";

describe("buildCaseComparisonHref", () => {
  it("encodes tenant and both case ids", () => {
    const href = buildCaseComparisonHref({ tenantId: "demo", caseA: "c1", caseB: "c2" });
    expect(href).toBe("/cases/compare?tenant_id=demo&case_a=c1&case_b=c2");
  });

  it("allows a single preset column", () => {
    const href = buildCaseComparisonHref({ tenantId: "acme", caseA: "case-uuid" });
    expect(href).toContain("tenant_id=acme");
    expect(href).toContain("case_a=case-uuid");
    expect(href).not.toContain("case_b");
  });
});
