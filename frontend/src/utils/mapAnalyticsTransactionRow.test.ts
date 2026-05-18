import { describe, expect, it } from "vitest";

import { mapAnalyticsTransactionRow } from "./mapAnalyticsTransactionRow";

describe("mapAnalyticsTransactionRow", () => {
  it("maps duck row with metadata decision", () => {
    const row = mapAnalyticsTransactionRow({
      ts: "2026-05-10T12:00:00",
      entity_id: "ent-1",
      amount: 42.5,
      country: "US",
      metadata: JSON.stringify({ trace_id: "tr-99", decision: "deny", channel: "wire" }),
    });
    expect(row).toMatchObject({
      traceId: "tr-99",
      entityId: "ent-1",
      amountCents: 4250,
      channel: "wire",
      status: "Block",
    });
  });
});
