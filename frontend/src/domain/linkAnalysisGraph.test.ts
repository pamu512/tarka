import { describe, expect, it } from "vitest";

import {
  attachDisplayRiskToNodes,
  buildRiskScoreByEntityId,
  LINK_ANALYSIS_MAX_NODES,
  normalizeRiskScore,
  pruneSubgraphForLinkView,
  riskFromNodeProperties,
} from "./linkAnalysisGraph";

describe("normalizeRiskScore", () => {
  it("maps 0–1 fractions to 0–100", () => {
    expect(normalizeRiskScore(0.5)).toBe(50);
    expect(normalizeRiskScore(1)).toBe(100);
  });
  it("passes through 0–100 scale", () => {
    expect(normalizeRiskScore(72.3)).toBe(72.3);
  });
});

describe("pruneSubgraphForLinkView", () => {
  const mk = (id: string) => ({ id, labels: ["X"], properties: {} });
  const edge = (a: string, b: string) => ({ from_id: a, to_id: b, type: "REL", properties: {} });

  it("returns all nodes when under cap", () => {
    const nodes = [mk("a"), mk("b")];
    const edges = [edge("a", "b")];
    const r = pruneSubgraphForLinkView(nodes, edges, "a", 10);
    expect(r.nodes).toHaveLength(2);
    expect(r.edges).toHaveLength(1);
    expect(r.originalNodeCount).toBe(2);
    expect(r.prunedNodeCount).toBe(2);
  });

  it("keeps seed and highest-degree nodes when over cap", () => {
    const hub = "hub";
    const nodes = [mk(hub), ...Array.from({ length: LINK_ANALYSIS_MAX_NODES + 5 }, (_, i) => mk(`n${i}`))];
    const edges: { from_id: string; to_id: string; type: string; properties: Record<string, unknown> }[] = [];
    for (let i = 0; i < LINK_ANALYSIS_MAX_NODES + 5; i++) {
      edges.push(edge(hub, `n${i}`));
    }
    const r = pruneSubgraphForLinkView(nodes, edges, hub, LINK_ANALYSIS_MAX_NODES);
    expect(r.originalNodeCount).toBe(nodes.length);
    expect(r.prunedNodeCount).toBe(LINK_ANALYSIS_MAX_NODES);
    expect(r.nodes.some((n) => n.id === hub)).toBe(true);
    expect(r.edges.every((e) => r.nodes.some((n) => n.id === e.from_id) && r.nodes.some((n) => n.id === e.to_id))).toBe(
      true,
    );
  });
});

describe("buildRiskScoreByEntityId", () => {
  it("merges anchor and propagation", () => {
    const m = buildRiskScoreByEntityId(
      { entity_id: "a", risk_score: 0.8, risk_factors: [], connected_flagged_count: 0, community_size: 1 },
      [{ entity_id: "b", entity_labels: [], propagated_risk_score: 0.5, distance: 1, path_description: "" }],
    );
    expect(m.get("a")).toBe(80);
    expect(m.get("b")).toBe(50);
  });
});

describe("attachDisplayRiskToNodes", () => {
  it("prefers analytics over vertex properties", () => {
    const nodes = [{ id: "a", labels: [], properties: { risk_score: 0.1 } }];
    const m = new Map<string, number>([["a", 90]]);
    const out = attachDisplayRiskToNodes(nodes, m);
    expect(out[0].displayRisk).toBe(90);
  });
});

describe("riskFromNodeProperties", () => {
  it("reads risk_score", () => {
    expect(riskFromNodeProperties({ risk_score: 0.42 })).toBe(42);
  });
});
