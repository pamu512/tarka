import { describe, expect, it } from "vitest";

import { deriveShortId, formatConfidence, toDisplayRow } from "./audit-recent-display";

describe("audit-recent-display", () => {
  it("derives short id from transaction_id", () => {
    expect(deriveShortId("00000000-0000-4000-8000-000000000001")).toBe("00000000");
  });

  it("maps API row to audit-first display", () => {
    const row = toDisplayRow({
      timestamp: "2026-01-01T00:00:00.000Z",
      transaction_id: "txn_abc",
      amount_cents: 100,
      status: "SHADOW_REVIEW",
      ai_confidence: 0.5,
    });
    expect(row.rule_result).toBe("SHADOW_REVIEW");
    expect(formatConfidence(row.ai_confidence)).toBe("50%");
  });
});
