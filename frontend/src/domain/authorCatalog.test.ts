import { describe, expect, it } from "vitest";

import { catalogFieldNames } from "./authorCatalog";
import { fallbackAuthorCatalog } from "./authorCatalogFallback";

describe("authorCatalog", () => {
  it("unions redis growth and payload names", () => {
    const names = catalogFieldNames({
      redis: [{ name: "event_count_7d", kind: "event_count", window_seconds: 604800 }],
      growth: [{ name: "relation_growth_1h", kind: "growth", window: "1h", threshold: 5 }],
      hops: [{ etype: "HAS_LIST" }],
      payload: [{ name: "amount" }],
    });
    expect(names.has("event_count_7d")).toBe(true);
    expect(names.has("relation_growth_1h")).toBe(true);
    expect(names.has("amount")).toBe(true);
    expect(names.has("HAS_LIST")).toBe(false);
  });

  it("fallback redis includes bundled manifest names and empty growth", () => {
    const cat = fallbackAuthorCatalog();
    const redis = new Set(cat.redis.map((r) => r.name));
    expect(redis.has("event_count_7d")).toBe(true);
    expect(redis.has("avg_amount_1h")).toBe(true);
    expect(cat.growth).toEqual([]);
    expect(new Set(cat.hops.map((h) => h.etype))).toEqual(
      new Set(["USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST"]),
    );
  });
});
