import { describe, expect, it } from "vitest";

import { fallbackAuthorCatalog } from "../domain/authorCatalogFallback";
import {
  leftoverHuntSearch,
  leftoverVisualHref,
  parseHopEtype,
  parseVelocityField,
} from "./leftoverVisualQuery";

const cat = {
  ...fallbackAuthorCatalog(),
  growth: [{ name: "relation_growth_1h", kind: "growth" as const, window: "1h", threshold: 5 }],
};

describe("leftoverVisualQuery", () => {
  it("parses shipped hop etypes only", () => {
    expect(parseHopEtype(cat, "has_etype:USES_DEVICE")).toBe("USES_DEVICE");
    expect(parseHopEtype(cat, "HAS_LIST")).toBe("HAS_LIST");
    expect(parseHopEtype(cat, "graph:missing")).toBe(null);
    expect(parseHopEtype(cat, "graph:unavailable")).toBe(null);
    expect(parseHopEtype(cat, "graph:empty")).toBe(null);
    expect(parseHopEtype(cat, "has_etype:FAKE")).toBe(null);
  });

  it("parses catalog redis and growth names only", () => {
    expect(parseVelocityField(cat, "event_count_7d")).toBe("event_count_7d");
    expect(parseVelocityField(cat, "relation_growth_1h")).toBe("relation_growth_1h");
    expect(parseVelocityField(cat, "rate")).toBe(null);
  });

  it("prefers hop over field on the visual href", () => {
    const href = leftoverVisualHref(cat, {
      leftoverId: "c1",
      pack: "device_signals",
      hits: "event_count_1h",
      hopNamed: "has_etype:HAS_LIST",
      entityId: "buyer-1",
      tenantId: "demo",
      decisionId: "dec:tr-1",
    });
    const q = new URLSearchParams(href.split("?")[1]);
    expect(href.startsWith("/rules/visual?")).toBe(true);
    expect(q.get("from")).toBe("leftover");
    expect(q.get("leftover_id")).toBe("c1");
    expect(q.get("pack")).toBe("device_signals");
    expect(q.get("hits")).toBe("event_count_1h");
    expect(q.get("etype")).toBe("HAS_LIST");
    expect(q.get("field")).toBe(null);
  });

  it("sets field on the visual href when no hop parses", () => {
    const href = leftoverVisualHref(cat, {
      leftoverId: "c1",
      pack: "device_signals",
      hits: "event_count_1h",
    });
    const q = new URLSearchParams(href.split("?")[1]);
    expect(q.get("from")).toBe("leftover");
    expect(q.get("etype")).toBe(null);
    expect(q.get("field")).toBe("event_count_1h");
  });

  it("builds Hunt search with leftover_id pack hits and decision_id", () => {
    const q = leftoverHuntSearch({
      case_id: "c1",
      entity_id: "buyer-1",
      tenant_id: "demo",
      trace_id: "tr-1",
      pack_id: "device_signals",
      rule_hits: ["event_count_1h", "sdk_bot"],
    });
    expect(q.get("entity_id")).toBe("buyer-1");
    expect(q.get("tenant_id")).toBe("demo");
    expect(q.get("decision_id")).toBe("dec:tr-1");
    expect(q.get("leftover_id")).toBe("c1");
    expect(q.get("pack")).toBe("device_signals");
    expect(q.get("hits")).toBe("event_count_1h,sdk_bot");
  });
});
