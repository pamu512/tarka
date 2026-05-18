import { describe, expect, it } from "vitest";

import type { AuditEntry } from "@/api/client";

import { buildShadowThoughtTrace, isDeterministicAiBypass } from "./shadow-thought-trace";

describe("buildShadowThoughtTrace", () => {
  it("uses explanation_drivers ranks as confidence weights", () => {
    const audit = {
      trace_id: "t1",
      entity_id: "e",
      tenant_id: "demo",
      event_type: "pay",
      decision: "review",
      score: 50,
      tags: [],
      rule_hits: [],
      created_at: "2026-01-01T00:00:00Z",
      explanation_drivers: [
        { reason: "r1", category: "rules", label: "L1", rank: 1, source: "driver_reasons" as const },
        { reason: "r2", category: "ml", label: "L2", rank: 2, source: "driver_explain" as const },
      ],
    } satisfies AuditEntry;
    const steps = buildShadowThoughtTrace(audit);
    expect(steps).toHaveLength(2);
    expect(steps[0]!.weight).toBeGreaterThan(steps[1]!.weight);
    expect(isDeterministicAiBypass(audit, steps)).toBe(false);
  });

  it("detects deterministic AI bypass when no narrative steps exist", () => {
    const audit = {
      trace_id: "t2",
      entity_id: "e",
      tenant_id: "demo",
      event_type: "pay",
      decision: "deny",
      score: 99,
      tags: [],
      rule_hits: ["hard_block"],
      created_at: "2026-01-01T00:00:00Z",
      explanation_drivers: [],
      inference_context: {
        schema_version: "3",
        driver_explain: [],
        ml_top_factors: [],
        ml_summary: null,
        driver_reasons: ["rule:block"],
      },
    } as AuditEntry;
    const steps = buildShadowThoughtTrace(audit);
    expect(steps).toHaveLength(0);
    expect(isDeterministicAiBypass(audit, steps)).toBe(true);
  });
});
