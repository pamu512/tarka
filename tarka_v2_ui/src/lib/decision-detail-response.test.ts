import { describe, expect, it } from "vitest";
import { normalizeDecisionDetailResponse } from "@/lib/decision-detail-response";

describe("normalizeDecisionDetailResponse", () => {
  it("accepts orchestrator-shaped payloads", () => {
    const out = normalizeDecisionDetailResponse({
      transaction_schema: {
        schema_version: "v2.1",
        transaction_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        amount_cents: 50000,
        currency: "USD",
        channel: "wire",
        merchant_id: "merch-1",
        instrument_fingerprint: "fp-1",
        ip_asn: "AS123",
        geo_country: "US",
        mcc: "5411",
        velocity_window_minutes: 15,
        prior_declines_24h: 0,
        metadata: { channel: "wire" },
      },
      shadow_decision: {
        model_id: "shadow-agent",
        shadow_verdict: "review",
        confidence: 0.42,
        risk_tags: ["velocity"],
        ai_reasoning: "Elevated velocity on fresh device.",
        latency_ms: 120,
        counterfactuals_considered: 2,
      },
      evaluation_trace: [{ rule_name: "demo", matched: true }],
    });
    expect(out?.transaction_schema.transaction_id).toBe("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
    expect(out?.shadow_decision.shadow_verdict).toBe("review");
    expect(out?.evaluation_trace).toHaveLength(1);
  });

  it("rejects incomplete payloads", () => {
    expect(normalizeDecisionDetailResponse({ transaction_schema: {} })).toBeNull();
  });
});
