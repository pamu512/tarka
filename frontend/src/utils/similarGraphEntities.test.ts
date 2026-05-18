import { describe, expect, it } from "vitest";

import type { RiskPropagationResult } from "../api/client";
import { normalizeSimilarEntities } from "./similarGraphEntities";

describe("normalizeSimilarEntities", () => {
  it("drops anchor and sorts by propagated score then distance", () => {
    const rows: RiskPropagationResult[] = [
      { entity_id: "a", entity_labels: [], propagated_risk_score: 0.5, distance: 2, path_description: "" },
      { entity_id: "seed", entity_labels: [], propagated_risk_score: 0.99, distance: 0, path_description: "anchor" },
      { entity_id: "b", entity_labels: [], propagated_risk_score: 0.8, distance: 2, path_description: "" },
      { entity_id: "c", entity_labels: [], propagated_risk_score: 0.8, distance: 1, path_description: "" },
    ];
    const out = normalizeSimilarEntities("seed", rows);
    expect(out.map((x) => x.entity_id)).toEqual(["c", "b", "a"]);
  });
});
