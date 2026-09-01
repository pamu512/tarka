import { describe, expect, it } from "vitest";
import type { GraphPathExplanation } from "../api/client";
import { LINK_ANALYSIS_MAX_NODES, undirectedLinkKey } from "./linkAnalysisGraph";
import {
  buildPersonHuntGraph,
  decisionToastText,
  filterReceiptLookback,
  filterWorkspaceNodes,
  graphLaggedEvaluate,
  hierarchyInstrumentFanout,
  lastOutcomeLabel,
  mergeSubgraphs,
  parseGraphWorkspaceParams,
  pathHighlightLinkKeys,
  pickHomePerson,
  rankRelatedLinks,
  searchHitMatchedOn,
  searchHitViaSubtitle,
  huntFetchTypes,
  seedInstrumentFanout,
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
    expect(p).toEqual({
      entityId: "a",
      tenantId: "acme",
      depth: 4,
      lookbackDays: 90,
      decisionId: "",
    });
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
  it("defaults lookback to 90 days and clamps to retention", () => {
    expect(parseGraphWorkspaceParams(new URLSearchParams(), "demo").lookbackDays).toBe(90);
    expect(parseGraphWorkspaceParams(new URLSearchParams("lookback_days=7"), "demo").lookbackDays).toBe(7);
    expect(parseGraphWorkspaceParams(new URLSearchParams("lookback_days=99999"), "demo").lookbackDays).toBe(2555);
  });
});

describe("pickHomePerson", () => {
  it("uses the last person as the key", () => {
    expect(
      pickHomePerson({
        lastEntityId: "buyer-demo",
        rows: [{ entity_id: "other", labels: ["Device"] }],
      }),
    ).toBe("buyer-demo");
  });
  it("prefers a Person row when there is no last person", () => {
    expect(
      pickHomePerson({
        rows: [
          { entity_id: "dev-1", labels: ["Device"] },
          { entity_id: "buyer-demo", labels: ["Person"] },
        ],
      }),
    ).toBe("buyer-demo");
  });
  it("returns empty when nothing to attach an event to", () => {
    expect(pickHomePerson({ rows: [] })).toBe("");
  });
  it("never treats an IP as the home person", () => {
    expect(
      pickHomePerson({
        lastEntityId: "ip:203.0.113.9",
        rows: [
          { entity_id: "ip:203.0.113.9", labels: ["Ip"] },
          { entity_id: "guest-aaa", labels: ["Person"] },
        ],
      }),
    ).toBe("guest-aaa");
  });
});

describe("rankRelatedLinks", () => {
  it("ranks payment above cafe IP", () => {
    const ranked = rankRelatedLinks(
      "guest-aaa",
      [
        { from_id: "guest-aaa", to_id: "ip:203.0.113.9", type: "USED_IP" },
        { from_id: "guest-aaa", to_id: "pay:1", type: "MADE_PAYMENT" },
      ],
      [
        {
          entity_id: "ip:203.0.113.9",
          entity_type: "Ip",
          importance: 8,
          reasons: ["type:ip"],
          attend_pack: false,
        },
        {
          entity_id: "pay:1",
          entity_type: "Payment",
          importance: 42,
          reasons: ["type:payment"],
          attend_pack: true,
        },
      ],
    );
    expect(ranked.map((r) => r.other)).toEqual(["pay:1", "ip:203.0.113.9"]);
  });

  it("does not throw when AGE edges omit from_id", () => {
    const ranked = rankRelatedLinks(
      "hunt-eval-buyer",
      [
        {
          from_id: undefined as unknown as string,
          to_id: undefined as unknown as string,
          type: "USED_DEVICE",
          startNode: "hunt-eval-buyer",
          endNode: "hunt-eval-device",
        } as { from_id: string; to_id: string; type: string; startNode: string; endNode: string },
        { from_id: "hunt-eval-buyer", to_id: "pay-hunt-eval-1", type: "MADE_PAYMENT" },
      ],
      null,
    );
    expect(ranked.map((r) => r.other)).toEqual(["hunt-eval-device", "pay-hunt-eval-1"]);
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

describe("searchHitMatchedOn", () => {
  it("names email and phone so the investigator sees how they found the Person", () => {
    expect(searchHitMatchedOn("email")).toBe("email");
    expect(searchHitMatchedOn("phone")).toBe("phone");
  });
  it("hides external_id — that is just the object id", () => {
    expect(searchHitMatchedOn("external_id")).toBeNull();
    expect(searchHitMatchedOn(undefined)).toBeNull();
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

describe("seedInstrumentFanout", () => {
  const now = Date.parse("2026-09-01T00:00:00Z");

  it("ranks attend_pack first, keeps Place and one Decision, drops Login", () => {
    const r = seedInstrumentFanout(
      "buyer",
      [
        n("buyer", { labels: ["Person"] }),
        n("dev-quiet", { labels: ["Device"] }),
        n("dev-hot", { labels: ["Device"] }),
        n("cell:3:1.2:3.4", { labels: ["Place"] }),
        n("login:tr", { labels: ["Login"] }),
        n("dec-old", {
          labels: ["Decision"],
          properties: { outcome: "allow", created_at: "2026-08-20T00:00:00Z" },
        }),
        n("dec-deny", {
          labels: ["Decision"],
          properties: { outcome: "deny", created_at: "2026-08-31T00:00:00Z" },
        }),
      ],
      [
        { from_id: "buyer", to_id: "dev-quiet", type: "USED_DEVICE" },
        { from_id: "buyer", to_id: "dev-hot", type: "USED_DEVICE" },
        { from_id: "buyer", to_id: "cell:3:1.2:3.4", type: "SEEN_AT" },
        { from_id: "buyer", to_id: "login:tr", type: "PERFORMED_LOGIN" },
        { from_id: "buyer", to_id: "dec-old", type: "RESULTED_IN" },
        { from_id: "buyer", to_id: "dec-deny", type: "RESULTED_IN" },
      ],
      [
        {
          entity_id: "dev-hot",
          entity_type: "Device",
          importance: 9,
          reasons: [],
          attend_pack: true,
        },
        {
          entity_id: "dev-quiet",
          entity_type: "Device",
          importance: 1,
          reasons: [],
          attend_pack: false,
        },
      ],
      { nowMs: now, lookbackDays: 90, max: 25, pinDecisionId: "dec-deny" },
    );
    expect(r.ids[0]).toBe("dev-hot");
    expect(r.ids).toContain("cell:3:1.2:3.4");
    expect(r.ids).toContain("dec-deny");
    expect(r.ids).not.toContain("dec-old");
    expect(r.ids).not.toContain("login:tr");
  });

  it("seeds Email Phone Document Card Address as durable ATO instruments", () => {
    const r = seedInstrumentFanout(
      "buyer",
      [
        n("buyer", { labels: ["Person"] }),
        n("email:sold@x.com", { labels: ["Email"] }),
        n("phone:+1", { labels: ["Phone"] }),
        n("passport-9", { labels: ["Document"] }),
        n("card:tok", { labels: ["Card"] }),
        n("addr:12 oak", { labels: ["Address"] }),
        n("list:NK-1", { labels: ["List"] }),
        n("login:tr", { labels: ["Login"] }),
      ],
      [
        { from_id: "buyer", to_id: "email:sold@x.com", type: "HAS_EMAIL" },
        { from_id: "buyer", to_id: "phone:+1", type: "HAS_PHONE" },
        { from_id: "buyer", to_id: "passport-9", type: "USED" },
        { from_id: "buyer", to_id: "card:tok", type: "USED" },
        { from_id: "buyer", to_id: "addr:12 oak", type: "USED" },
        { from_id: "buyer", to_id: "list:NK-1", type: "HAS_LIST" },
        { from_id: "buyer", to_id: "login:tr", type: "PERFORMED_LOGIN" },
      ],
      null,
      { nowMs: now, lookbackDays: 90, max: 25 },
    );
    expect(r.ids).toEqual(
      expect.arrayContaining([
        "email:sold@x.com",
        "phone:+1",
        "passport-9",
        "card:tok",
        "addr:12 oak",
        "list:NK-1",
      ]),
    );
    expect(r.ids).not.toContain("login:tr");
  });

  it("Person seed ring does not pick neighboring Persons", () => {
    const r = seedInstrumentFanout(
      "acct-old",
      [
        n("acct-old", { labels: ["Person"] }),
        n("acct-new", { labels: ["Person"] }),
        n("email:sold@x.com", { labels: ["Email"] }),
      ],
      [
        { from_id: "acct-old", to_id: "email:sold@x.com", type: "HAS_EMAIL" },
        { from_id: "acct-new", to_id: "email:sold@x.com", type: "HAS_EMAIL" },
      ],
      null,
      { nowMs: now, lookbackDays: 90, max: 25 },
    );
    expect(r.ids).toContain("email:sold@x.com");
    expect(r.ids).not.toContain("acct-new");
  });
});

describe("huntFetchTypes", () => {
  it("includes Person so an Email seed can show both owners", () => {
    expect(huntFetchTypes()).toContain("Person");
    expect(huntFetchTypes()).toContain("Email");
    expect(huntFetchTypes()).toContain("List");
    expect(huntFetchTypes()).toContain("Decision");
  });
});

describe("filterReceiptLookback", () => {
  const now = Date.parse("2026-09-01T00:00:00Z");

  it("drops old Login, keeps Device and undated Login", () => {
    const r = filterReceiptLookback(
      [
        n("buyer", { labels: ["Person"] }),
        n("dev-1", { labels: ["Device"] }),
        n("login:old", {
          labels: ["Login"],
          properties: { created_at: "2025-01-01T00:00:00Z" },
        }),
        n("login:undated", { labels: ["Login"] }),
      ],
      [
        { from_id: "buyer", to_id: "dev-1", type: "USED_DEVICE" },
        { from_id: "buyer", to_id: "login:old", type: "PERFORMED_LOGIN" },
        { from_id: "buyer", to_id: "login:undated", type: "PERFORMED_LOGIN" },
      ],
      { seedId: "buyer", lookbackDays: 90, nowMs: now },
    );
    const ids = r.nodes.map((x) => x.id).sort();
    expect(ids).toEqual(["buyer", "dev-1", "login:undated"]);
  });
});

describe("buildPersonHuntGraph", () => {
  it("keeps the instrument tree and Person-RESULTED_IN-Decision hops", () => {
    const r = buildPersonHuntGraph(
      "buyer",
      {
        nodes: [
          n("buyer", { labels: ["Person"] }),
          n("dev-1", { labels: ["Device"] }),
          n("pay-1", { labels: ["Payment"] }),
          n("login:tr", { labels: ["Login"] }),
          n("dec-hold", { labels: ["Decision"] }),
        ],
        edges: [
          { from_id: "buyer", to_id: "dev-1", type: "USED_DEVICE" },
          { from_id: "buyer", to_id: "pay-1", type: "MADE_PAYMENT" },
          { from_id: "buyer", to_id: "login:tr", type: "PERFORMED_LOGIN" },
          { from_id: "buyer", to_id: "dec-hold", type: "RESULTED_IN" },
        ],
      },
      [
        {
          nodes: [
            n("dev-1", { labels: ["Device"] }),
            n("ip:1", { labels: ["Ip"] }),
            n("dec-login", { labels: ["Decision"] }),
          ],
          edges: [
            { from_id: "dev-1", to_id: "ip:1", type: "USED_IP" },
            { from_id: "dev-1", to_id: "dec-login", type: "RESULTED_IN" },
          ],
        },
        {
          nodes: [
            n("pay-1", { labels: ["Payment"] }),
            n("ip:2", { labels: ["Ip"] }),
            n("dec-pay", { labels: ["Decision"] }),
          ],
          edges: [
            { from_id: "pay-1", to_id: "ip:2", type: "USED_IP" },
            { from_id: "pay-1", to_id: "dec-pay", type: "RESULTED_IN" },
          ],
        },
      ],
      50,
    );
    const ids = r.nodes.map((x) => x.id).sort();
    expect(ids).toEqual([
      "buyer",
      "dec-hold",
      "dec-login",
      "dec-pay",
      "dev-1",
      "ip:1",
      "ip:2",
      "login:tr",
      "pay-1",
    ]);
  });
});

describe("decisionToastText", () => {
  it("toasts the last outcome on the object, not a graph node", () => {
    expect(
      decisionToastText(
        n("dev-1", { labels: ["Device"], properties: { last_outcome: "deny", last_trace_id: "tr-1" } }),
      ),
    ).toBe("deny");
    expect(decisionToastText(n("dev-1", { labels: ["Device"], properties: {} }))).toBeNull();
  });
});

describe("lastOutcomeLabel", () => {
  it("labels missing last_outcome as unknown, not allow", () => {
    expect(lastOutcomeLabel(n("p", { properties: {} }))).toBe("unknown");
    expect(lastOutcomeLabel(n("p", { properties: { last_outcome: "deny" } }))).toBe("deny");
    expect(lastOutcomeLabel({ last_outcome: "allow" })).toBe("allow");
  });
});

describe("hierarchyInstrumentFanout", () => {
  it("counts instruments before the cap", () => {
    const nodes = [
      n("buyer", { labels: ["Person"] }),
      ...Array.from({ length: 10 }, (_, i) => n(`dev-${i}`, { labels: ["Device"] })),
    ];
    const edges = Array.from({ length: 10 }, (_, i) => ({
      from_id: "buyer",
      to_id: `dev-${i}`,
      type: "USES_DEVICE",
    }));
    const r = hierarchyInstrumentFanout("buyer", nodes, edges);
    expect(r.total).toBe(10);
    expect(r.ids).toHaveLength(8);
  });
});

describe("graphLaggedEvaluate", () => {
  it("lags when latest trace is not on the object", () => {
    expect(
      graphLaggedEvaluate({ trace_id: "tr-new" }, { last_trace_id: "tr-old", trace_ids: ["tr-old"] }),
    ).toBe(true);
    expect(
      graphLaggedEvaluate({ trace_id: "tr-old" }, { last_trace_id: "tr-old", trace_ids: ["tr-old"] }),
    ).toBe(false);
    expect(graphLaggedEvaluate(null, { last_trace_id: "tr-old", trace_ids: [] })).toBe(false);
  });
});
