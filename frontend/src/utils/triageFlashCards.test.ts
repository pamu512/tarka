import { describe, expect, it } from "vitest";
import { buildLoyaltyFlashCard, buildTriageFlashCards } from "./triageFlashCards";

describe("buildTriageFlashCards", () => {
  it("returns four cards in Velocity, Graph, Loyalty, Geo order", () => {
    const [v, g, loyalty, geo] = buildTriageFlashCards(null, null, null);
    expect(v.title).toBe("Velocity");
    expect(g.title).toBe("Graph");
    expect(loyalty.title).toBe("Loyalty");
    expect(loyalty.value).toBe("Feeds req.");
    expect(geo.title).toBe("Geo (enrichment)");
  });

  it("surfaces loyalty friction tags as Friction / Restricted", () => {
    const [, , friction] = buildTriageFlashCards(null, null, ["loyalty:friction:step_up"]);
    expect(friction.value).toBe("Friction");
    expect(friction.tone).toBe("warn");
    const [, , restricted] = buildTriageFlashCards(null, null, ["loyalty:friction:block"]);
    expect(restricted.value).toBe("Restricted");
    expect(restricted.tone).toBe("critical");
  });
});

describe("buildLoyaltyFlashCard", () => {
  it("is neutral when tags are empty", () => {
    expect(buildLoyaltyFlashCard([])).toEqual({
      title: "Loyalty",
      value: "Feeds req.",
      tone: "neutral",
    });
  });
});
