import { describe, expect, it } from "vitest";
import { extractGeoCollisionModel, haversineKm } from "./geoCollisionExtract";

describe("haversineKm", () => {
  it("SF to LA is roughly 550km", () => {
    const km = haversineKm(
      { lat: 37.7749, lng: -122.4194 },
      { lat: 34.0522, lng: -118.2437 },
    );
    expect(km).toBeGreaterThan(500);
    expect(km).toBeLessThan(600);
  });
});

describe("extractGeoCollisionModel", () => {
  it("reads geo_collision block", () => {
    const m = extractGeoCollisionModel({
      geo_collision: {
        ip: { lat: 37.77, lng: -122.42, label: "IP" },
        shipping: { lat: 34.05, lng: -118.24, label: "Ship" },
      },
    });
    expect(m?.precision).toBe("coordinates");
    expect(m?.ip.label).toBe("IP");
    expect(m?.straightLineKm).toBeGreaterThan(100);
  });

  it("falls back to country centroids when distinct", () => {
    const m = extractGeoCollisionModel({
      geo_country: "US",
      shipping_country: "FR",
    });
    expect(m?.precision).toBe("country_centroid");
    expect(m?.ip.label).toContain("US");
    expect(m?.shipping.label).toContain("FR");
  });

  it("returns null when only same country available", () => {
    expect(extractGeoCollisionModel({ geo_country: "US", shipping_country: "US" })).toBeNull();
  });
});
