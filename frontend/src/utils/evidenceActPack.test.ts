import { describe, expect, it } from "vitest";
import { buildEvidenceActPack } from "./evidenceActPack";

describe("buildEvidenceActPack", () => {
  it("builds act pack from bundle + explain", () => {
    const pack = buildEvidenceActPack(
      {
        tenant_id: "t1",
        case: { id: "c1", tenant_id: "t1", entity_id: "e1", trace_id: "tr1" },
        decision_audit: { decision: "review", score: 72, recommended_action: "manual_review" },
        evidence_bundle_v1: { content_sha256: "abc" },
      },
      {
        decisionExplain: {
          decision: "review",
          score: 72,
          recommended_action: "manual_review",
          inference_context: {
            confidence_tier: "medium",
            driver_reasons: ["device_tamper_or_emulator_signals"],
          },
        },
      },
    );
    expect(pack.schema_id).toBe("tarka.evidence_act_pack/v1");
    expect(pack.content_sha256).toBe("abc");
    expect(pack.recommended_action).toBe("manual_review");
    expect(pack.top_drivers).toContain("device_tamper_or_emulator_signals");
    expect(pack.suggested_next).toContain("sar_generate");
    expect(pack.suggested_next).toContain("dispute_open");
  });
});
