import { describe, expect, it } from "vitest";
import { buildTriageFlashCards } from "./triageFlashCards";

describe("buildTriageFlashCards", () => {
  it("returns three cards in Velocity, Graph, Geo order", () => {
    const [v, g, geo] = buildTriageFlashCards(null, null);
    expect(v.title).toBe("Velocity");
    expect(g.title).toBe("Graph");
    expect(geo.title).toBe("Geo (enrichment)");
  });
});
