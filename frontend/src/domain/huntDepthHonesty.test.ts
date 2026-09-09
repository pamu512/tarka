import { describe, expect, it } from "vitest";

import {
  AGE_HUNT_DEPTH_MAX,
  DEPTH_NOT_YET_REPORTED,
  HUNT_DEPTH_CAPPED,
  readHuntDepthFromPayload,
  resolveHuntDepthHonesty,
} from "./huntDepthHonesty";

const FORBIDDEN = [
  /neo4j[- ]class/i,
  /unlimited path/i,
  /variable-length path/i,
  /identity SKU/i,
  /\b(sift|forter|riskified|feedzai|featurespace|unit21|sardine|datavisor)\b/i,
];

describe("resolveHuntDepthHonesty", () => {
  it("empty GRAPH_SERVICE_URL is Hunt/graph plane-off English, no invented hops", () => {
    const row = resolveHuntDepthHonesty({ graphServiceUrl: "", depthRequested: 3 });
    expect(row.planeOff).toBe(true);
    expect(row.banner).toMatch(/GRAPH_SERVICE_URL is empty/i);
    expect(row.banner).toMatch(/Hunt/i);
    expect(row.banner).toMatch(/hops are off/i);
    expect(row.banner).toMatch(/does not invent neighbors/i);
    expect(row.depth_applied).toBeNull();
    expect(row.appliedLabel).toBe(DEPTH_NOT_YET_REPORTED);
  });

  it("depth_requested above AGE-safe max degrades with applied + reason", () => {
    const stub = resolveHuntDepthHonesty({
      graphServiceUrl: "http://graph-service:8001",
      depthRequested: 4,
    });
    expect(AGE_HUNT_DEPTH_MAX).toBe(1);
    expect(stub.degraded).toBe(true);
    expect(stub.depth_requested).toBe(4);
    expect(stub.depth_applied).toBeNull();
    expect(stub.appliedLabel).toBe(DEPTH_NOT_YET_REPORTED);
    expect(stub.degrade_reason).toBe(HUNT_DEPTH_CAPPED);
    expect(stub.banner).toMatch(/requested 4/i);
    expect(stub.banner).toMatch(/depth not yet reported/i);
    expect(stub.banner).toMatch(/hunt:depth_capped/);

    const fromApi = resolveHuntDepthHonesty({
      graphServiceUrl: "http://graph-service:8001",
      depthRequested: 4,
      api: {
        hunt_depth_max: 1,
        depth_requested: 4,
        depth_applied: 1,
        degrade_reason: HUNT_DEPTH_CAPPED,
      },
    });
    expect(fromApi.degraded).toBe(true);
    expect(fromApi.depth_applied).toBe(1);
    expect(fromApi.appliedLabel).toBe("1");
    expect(fromApi.degrade_reason).toBe(HUNT_DEPTH_CAPPED);
    expect(fromApi.banner).toMatch(/applied 1/);
  });

  it("does not invent hop counts when the payload has no depth fields", () => {
    expect(readHuntDepthFromPayload({ nodes: [], edges: [] })).toBeNull();
    const row = resolveHuntDepthHonesty({
      graphServiceUrl: "http://graph-service:8001",
      depthRequested: 1,
      api: readHuntDepthFromPayload({ nodes: [{ id: "a" }], edges: [] }),
    });
    expect(row.depth_applied).toBeNull();
    expect(row.appliedLabel).toBe(DEPTH_NOT_YET_REPORTED);
    expect(row.degraded).toBe(false);
  });

  it("copy never says Neo4j-class / unlimited path / identity SKU / named incumbents", () => {
    const blobs = [
      resolveHuntDepthHonesty({ graphServiceUrl: "", depthRequested: 2 }).banner,
      resolveHuntDepthHonesty({ graphServiceUrl: "http://g", depthRequested: 5 }).banner,
      resolveHuntDepthHonesty({
        graphServiceUrl: "http://g",
        depthRequested: 3,
        api: { depth_requested: 3, depth_applied: 1, degrade_reason: HUNT_DEPTH_CAPPED },
      }).banner,
    ].join("\n");
    for (const pat of FORBIDDEN) {
      expect(blobs).not.toMatch(pat);
    }
  });
});
