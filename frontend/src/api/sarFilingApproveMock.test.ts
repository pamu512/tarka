import { describe, expect, it } from "vitest";

import { assertHumanActorIdForSarFiling, getMockResponse } from "./mockData";

describe("assertHumanActorIdForSarFiling", () => {
  it("rejects missing actor_id", () => {
    expect(() => assertHumanActorIdForSarFiling({})).toThrow(/422/);
    expect(() => assertHumanActorIdForSarFiling({ actor_id: "" })).toThrow(/422/);
    expect(() => assertHumanActorIdForSarFiling({ actor_id: "   " })).toThrow(/422/);
  });

  it("rejects known automated actor ids", () => {
    expect(() => assertHumanActorIdForSarFiling({ actor_id: "sar_worker" })).toThrow(/422/);
  });

  it("accepts a human analyst id", () => {
    expect(assertHumanActorIdForSarFiling({ actor_id: "analyst.jdoe" })).toBe("analyst.jdoe");
  });
});

describe("getMockResponse SAR approve → FILED", () => {
  it("refuses FILED transition without a human actor_id", () => {
    const caseId = `sar-mock-gate-${Date.now()}`;
    const base = `/api/cases/v1/cases/${caseId}/sar/intents`;
    getMockResponse(`${base}?tenant_id=demo`, { method: "GET" });
    const listed = getMockResponse(`${base}?tenant_id=demo`, { method: "GET" }) as {
      intents: Array<{ id: string; status: string }>;
    };
    const intentId = listed.intents[0]!.id;
    const approvePath = `/api/cases/v1/cases/${caseId}/sar/intents/${intentId}/approve?tenant_id=demo`;
    expect(() => getMockResponse(approvePath, { method: "POST", body: "{}" })).toThrow(/422/);
    expect(() =>
      getMockResponse(approvePath, { method: "POST", body: JSON.stringify({ actor_id: "sar_worker" }) }),
    ).toThrow(/422/);
  });

  it("sets FILED when actor_id is a human id", () => {
    const caseId = `sar-mock-ok-${Date.now()}`;
    const base = `/api/cases/v1/cases/${caseId}/sar/intents`;
    getMockResponse(`${base}?tenant_id=demo`, { method: "GET" });
    const listed = getMockResponse(`${base}?tenant_id=demo`, { method: "GET" }) as {
      intents: Array<{ id: string; status: string }>;
    };
    const intentId = listed.intents[0]!.id;
    const approvePath = `/api/cases/v1/cases/${caseId}/sar/intents/${intentId}/approve?tenant_id=demo`;
    const out = getMockResponse(approvePath, {
      method: "POST",
      body: JSON.stringify({ actor_id: "compliance.analyst_7" }),
    }) as { status: string; sar_filing_intent_id: string };
    expect(out.status).toBe("FILED");
    expect(out.sar_filing_intent_id).toBe(intentId);
    const detail = getMockResponse(
      `/api/cases/v1/cases/${caseId}/sar/intents/${intentId}/detail?tenant_id=demo`,
      { method: "GET" },
    ) as { status: string; audit_log: Array<{ to_status: string; actor: string | null }> };
    expect(detail.status).toBe("FILED");
    const filedRow = detail.audit_log.filter((r) => r.to_status === "FILED").pop();
    expect(filedRow?.actor).toBe("compliance.analyst_7");
  });
});
