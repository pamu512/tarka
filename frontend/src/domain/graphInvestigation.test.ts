import { describe, expect, it } from "vitest";
import type { GraphPathExplanation } from "../api/client";
import { LINK_ANALYSIS_MAX_NODES, undirectedLinkKey } from "./linkAnalysisGraph";
import {
  filterWorkspaceNodes,
  mergeSubgraphs,
  parseGraphWorkspaceParams,
  pathHighlightLinkKeys,
  searchHitViaSubtitle,
  storedDisplayRisk,
  typeHistogram,
} from "./graphInvestigation";

const n = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  labels: (extra.labels as string[]) ?? ["Person"],
  properties: {},
  ...extra,
});
const e = (a: string, b: string) => ({ from_id: a, to_id: b, type: "KNOWS" });

describe("parseGraphWorkspaceParams", () => {
  it("reads entity_id / tenant_id / depth", () => {
    const p = parseGraphWorkspaceParams(
      new URLSearchParams("entity_id=a&tenant_id=acme&depth=4"),
      "demo",
    );
    expect(p).toEqual({ entityId: "a", tenantId: "acme", depth: 4 });
  });
  it("accepts entity / tenant aliases", () => {
    const p = parseGraphWorkspaceParams(new URLSearchParams("entity=a&tenant=acme"), "demo");
    expect(p.entityId).toBe("a");
    expect(p.tenantId).toBe("acme");
    expect(p.depth).toBe(2);
  });
  it("clamps depth 1–5", () => {
    expect(parseGraphWorkspaceParams(new URLSearchParams("depth=9"), "demo").depth).toBe(5);
    expect(parseGraphWorkspaceParams(new URLSearchParams("depth=0"), "demo").depth).toBe(1);
  });
});

describe("storedDisplayRisk", () => {
  it("null when unscored", () => {
    expect(storedDisplayRisk(n("a", { scored: false, risk_score: null }))).toBeNull();
  });
  it("0 when scored 0", () => {
    expect(storedDisplayRisk(n("a", { scored: true, risk_score: 0 }))).toBe(0);
  });
});

describe("filterWorkspaceNodes", () => {
  const nodes = [
    n("p", { labels: ["Person"], scored: true, risk_score: 80, relation_growth_1h: 6, relation_growth_24h: 6 }),
    n("d", { labels: ["Device"], scored: false, risk_score: null, relation_growth_1h: null, relation_growth_24h: null }),
    n("c", { labels: ["Person"], scored: true, risk_score: 0, relation_growth_1h: 0, relation_growth_24h: 0 }),
  ];
  const edges = [e("p", "d"), e("p", "c")];

  it("hides other types", () => {
    const r = filterWorkspaceNodes(nodes, edges, {
      types: ["Device"], minRisk: null, scoredOnly: false, growthOnly: false,
    });
    expect(r.nodes.map((x) => x.id)).toEqual(["d"]);
    expect(r.edges).toHaveLength(0);
  });

  it("keeps unscored under minRisk unless scoredOnly", () => {
    const r = filterWorkspaceNodes(nodes, edges, {
      types: null, minRisk: 10, scoredOnly: false, growthOnly: false,
    });
    expect(r.nodes.map((x) => x.id).sort()).toEqual(["d", "p"]);
    const only = filterWorkspaceNodes(nodes, edges, {
      types: null, minRisk: 10, scoredOnly: true, growthOnly: false,
    });
    expect(only.nodes.map((x) => x.id)).toEqual(["p"]);
  });

  it("growth toggle hides null growth", () => {
    const r = filterWorkspaceNodes(nodes, edges, {
      types: null, minRisk: null, scoredOnly: false, growthOnly: true,
    });
    expect(r.nodes.map((x) => x.id)).toEqual(["p"]);
  });
});

describe("mergeSubgraphs", () => {
  it("unions without duplicate edges and keeps seed", () => {
    const r = mergeSubgraphs(
      "seed",
      { nodes: [n("seed"), n("a")], edges: [e("seed", "a")] },
      { nodes: [n("a"), n("b")], edges: [e("seed", "a"), e("a", "b")] },
      10,
    );
    expect(r.nodes.map((x) => x.id).sort()).toEqual(["a", "b", "seed"]);
    expect(r.edges).toHaveLength(2);
    expect(r.prunedNodeCount).toBe(3);
  });

  it("prunes toward seed at cap", () => {
    const extraNodes = Array.from({ length: LINK_ANALYSIS_MAX_NODES + 5 }, (_, i) => n(`n${i}`));
    const extraEdges = extraNodes.map((node) => e("seed", node.id));
    const r = mergeSubgraphs(
      "seed",
      { nodes: [n("seed")], edges: [] },
      { nodes: extraNodes, edges: extraEdges },
      LINK_ANALYSIS_MAX_NODES,
    );
    expect(r.prunedNodeCount).toBe(LINK_ANALYSIS_MAX_NODES);
    expect(r.nodes.some((x) => x.id === "seed")).toBe(true);
  });
});

describe("pathHighlightLinkKeys", () => {
  const expl = (hops: Array<{ entity_id: string; relationship?: string | null }>): GraphPathExplanation => ({
    schema_id: "tarka.graph_path_explanation/v1",
    tenant_id: "t",
    subject: "seed",
    target: "c",
    paths: [
      {
        entity_id: "c",
        target_entity_id: "c",
        distance: Math.max(0, hops.length - 1),
        propagated_risk_score: 1,
        path_description: "",
        hops,
        reasons: [],
      },
    ],
    risk_narrative: "",
    summary: {},
  });

  it("builds undirected keys for consecutive hops", () => {
    const keys = pathHighlightLinkKeys(
      expl([
        { entity_id: "seed", relationship: null },
        { entity_id: "b", relationship: "KNOWS" },
        { entity_id: "c", relationship: "HAS" },
      ]),
    );
    expect(keys.has(undirectedLinkKey("seed", "b"))).toBe(true);
    expect(keys.has(undirectedLinkKey("b", "c"))).toBe(true);
    expect(keys.has(undirectedLinkKey("b", "seed"))).toBe(true);
    expect(keys.size).toBe(2);
  });

  it("skips hops with empty entity ids", () => {
    const keys = pathHighlightLinkKeys(
      expl([{ entity_id: "seed" }, { entity_id: "" }, { entity_id: "c" }]),
    );
    expect(keys.size).toBe(0);
  });
});

describe("searchHitViaSubtitle", () => {
  it("formats via label and id", () => {
    expect(searchHitViaSubtitle({ entity_id: "alice@acme.com", labels: ["Email"] })).toBe(
      "via Email alice@acme.com",
    );
  });
  it("null when via missing", () => {
    expect(searchHitViaSubtitle(null)).toBeNull();
    expect(searchHitViaSubtitle(undefined)).toBeNull();
    expect(searchHitViaSubtitle({ entity_id: "", labels: ["Email"] })).toBeNull();
  });
  it("falls back to Custom when labels empty", () => {
    expect(searchHitViaSubtitle({ entity_id: "dev-1", labels: [] })).toBe("via Custom dev-1");
  });
});

describe("typeHistogram", () => {
  it("counts primary labels on loaded set", () => {
    const h = typeHistogram([n("a", { labels: ["Person"] }), n("b", { labels: ["Person"] }), n("c", { labels: ["Device"] })]);
    expect(h).toEqual([
      { label: "Person", count: 2 },
      { label: "Device", count: 1 },
    ]);
  });
});
