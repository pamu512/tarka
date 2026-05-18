import { NextResponse } from "next/server";
import type { DecisionDetailResponse } from "@/types/decision-detail";

function mockDecision(transactionId: string): DecisionDetailResponse {
  const amountSeed =
    Array.from(transactionId).reduce((a, c) => a + c.charCodeAt(0), 0) % 400_000;

  const transaction_schema: DecisionDetailResponse["transaction_schema"] = {
    schema_version: "v2.1",
    transaction_id: transactionId,
    amount_cents: amountSeed + 12_500,
    currency: "USD",
    channel: "card_not_present",
    merchant_id: "merch_shadow_lab",
    instrument_fingerprint: `fp_${transactionId.slice(-12)}`,
    ip_asn: "AS7922",
    geo_country: "US",
    mcc: "5411",
    velocity_window_minutes: 15,
    prior_declines_24h: 1,
    metadata: {
      device_behavior_score: 0.42,
      list_match: "none",
      session_age_sec: 128,
    },
  };

  const shadow_decision: DecisionDetailResponse["shadow_decision"] = {
    model_id: "shadow-gpt-fraud-v4",
    shadow_verdict: "elevated_risk",
    confidence: 0.87,
    risk_tags: ["velocity", "geo_mismatch", "mcc_drift"],
    ai_reasoning: [
      "Initial cohort: merchant velocity within 2σ of baseline for this MCC.",
      {
        step: "Feature cross-check",
        text: "BIN geography diverges from historical cardholder region; weight +0.12.",
      },
      {
        step: "Policy synthesis",
        detail:
          "Rules engine suggested FLAG; shadow agrees with emphasis on locality and fresh device fingerprint.",
      },
      "Final stance: route to SHADOW_REVIEW so an analyst can confirm Prompt-7 forensic constraints.",
    ],
    latency_ms: 184,
    counterfactuals_considered: 6,
  };

  const evaluation_trace = [
    {
      rule_id: "00000000-0000-0000-0000-00000000c0df",
      rule_name: "demo_high_amount_shadow_review",
      matched: true,
      priority: 10,
      action: "SHADOW_REVIEW",
    },
    {
      rule_id: "00000000-0000-0000-0000-00000000c0de",
      rule_name: "demo_stress_block_lane",
      matched: false,
      priority: 5,
      action: null,
    },
  ];

  return { transaction_schema, shadow_decision, evaluation_trace };
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ transactionId: string }> },
) {
  const { transactionId: rawId } = await context.params;
  const transactionId = decodeURIComponent(rawId);

  if (!transactionId || transactionId.length > 512) {
    return NextResponse.json({ error: "invalid transaction id" }, { status: 400 });
  }

  const body = mockDecision(transactionId);
  return NextResponse.json(body, { headers: { "Cache-Control": "no-store" } });
}
