import { describe, expect, it } from "vitest";
import {
  buildLoyaltyFlashCard,
  buildTriageFlashCards,
  extractLoyaltyEconomicsGates,
} from "./triageFlashCards";

describe("buildLoyaltyFlashCard", () => {
  it("missing gates → Feeds req. neutral", () => {
    expect(buildLoyaltyFlashCard(null)).toEqual({
      title: "Loyalty",
      value: "Feeds req.",
      tone: "neutral",
    });
  });

  it("feeds_missing / config_missing → Feeds req. neutral", () => {
    expect(buildLoyaltyFlashCard({ status: "feeds_missing" })).toMatchObject({
      value: "Feeds req.",
      tone: "neutral",
    });
    expect(buildLoyaltyFlashCard({ status: "config_missing" })).toMatchObject({
      value: "Feeds req.",
      tone: "neutral",
    });
  });

  it("any ok gate ineligible → Restricted warn", () => {
    const card = buildLoyaltyFlashCard({
      status: "ok",
      gates: {
        dispatch: { eligible: true, status: "ok" },
        redeem: { eligible: false, status: "ok" },
        order: { eligible: true, status: "ok" },
      },
    });
    expect(card).toEqual({ title: "Loyalty", value: "Restricted", tone: "warn" });
  });

  it("all ok gates eligible → Eligible ok", () => {
    const card = buildLoyaltyFlashCard({
      status: "ok",
      gates: {
        dispatch: { eligible: true, status: "ok" },
        redeem: { eligible: true, status: "ok" },
        order: { eligible: true, status: "ok" },
      },
    });
    expect(card).toEqual({ title: "Loyalty", value: "Eligible", tone: "ok" });
  });
});

describe("extractLoyaltyEconomicsGates", () => {
  it("reads direct and nested payload_snapshot paths", () => {
    const gates = { status: "ok", gates: {} };
    expect(extractLoyaltyEconomicsGates({ loyalty_economics_gates: gates })).toBe(gates);
    expect(
      extractLoyaltyEconomicsGates({ payload_snapshot: { loyalty_economics_gates: gates } }),
    ).toBe(gates);
  });
});

describe("buildTriageFlashCards", () => {
  it("returns four cards in Velocity, Graph, Loyalty, Geo order", () => {
    const [v, g, l, geo] = buildTriageFlashCards(null, null, null);
    expect(v.title).toBe("Velocity");
    expect(g.title).toBe("Graph");
    expect(l.title).toBe("Loyalty");
    expect(geo.title).toBe("Geo (enrichment)");
  });
});
