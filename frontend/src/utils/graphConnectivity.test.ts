import { describe, expect, it } from "vitest";
import { parseConnectivityNeighborCount } from "./graphConnectivity";

describe("parseConnectivityNeighborCount", () => {
  it("reads high_connectivity count", () => {
    expect(parseConnectivityNeighborCount(["high_connectivity:14", "other"])).toBe(14);
  });

  it("reads moderate_connectivity count", () => {
    expect(parseConnectivityNeighborCount(["moderate_connectivity:3"])).toBe(3);
  });

  it("returns null when absent", () => {
    expect(parseConnectivityNeighborCount([])).toBeNull();
    expect(parseConnectivityNeighborCount(["mule_pattern"])).toBeNull();
  });
});
