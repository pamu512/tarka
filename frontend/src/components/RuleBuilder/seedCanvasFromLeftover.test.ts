import { describe, expect, it } from "vitest";

import { fallbackAuthorCatalog } from "../../domain/authorCatalogFallback";
import { seedCanvasFromLeftover } from "./seedCanvasFromLeftover";

const cat = {
  ...fallbackAuthorCatalog(),
  growth: [{ name: "relation_growth_1h", kind: "growth" as const, window: "1h", threshold: 5 }],
};

describe("seedCanvasFromLeftover", () => {
  it("returns null when from is not leftover", () => {
    expect(seedCanvasFromLeftover(cat, new URLSearchParams("etype=HAS_LIST"))).toBe(null);
    expect(seedCanvasFromLeftover(cat, new URLSearchParams("from=hunt&etype=HAS_LIST"))).toBe(null);
  });

  it("seeds HAS_LIST hop when etype is shipped", () => {
    const seeded = seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover&etype=HAS_LIST"));
    expect(seeded!.nodes.some((n) => n.type === "hopEtype" && (n.data as { etype: string }).etype === "HAS_LIST")).toBe(true);
    expect(seeded!.nodes.some((n) => n.type === "ruleRoot")).toBe(true);
    expect(
      seeded!.edges.some((e) => e.sourceHandle === "he-out" && e.targetHandle === "r-in"),
    ).toBe(true);
  });

  it("does not seed a hop for etype=NOPE", () => {
    expect(seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover&etype=NOPE"))).toBe(null);
  });

  it("seeds growth feature when field is in catalog", () => {
    const seeded = seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover&field=relation_growth_1h"));
    expect(seeded!.nodes.some((n) => n.type === "feature" && (n.data as { field: string }).field === "relation_growth_1h")).toBe(true);
    expect(
      seeded!.nodes.some((n) => n.type === "operator" && (n.data as { op: string; valueStr: string }).op === "gte" && (n.data as { valueStr: string }).valueStr === "0"),
    ).toBe(true);
    expect(seeded!.nodes.some((n) => n.type === "ruleRoot")).toBe(true);
  });

  it("returns null when leftover has no shipped hop or catalog field", () => {
    expect(seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover"))).toBe(null);
  });
});
