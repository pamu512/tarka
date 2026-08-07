import { describe, expect, it } from "vitest";
import { deskStrictEnabled, isDeskApiPath, mocksAllowedForUrl } from "./deskMockPolicy";

describe("deskMockPolicy", () => {
  it("identifies desk API paths", () => {
    expect(isDeskApiPath("/api/cases/v1/cases/ops/kpis?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/cases/v1/cases/ops/qa-metrics?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/decisions/v1/ops/calibration-status?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/decisions/v1/calibration/reliability-bins")).toBe(true);
    expect(isDeskApiPath("/api/graph/v1/entities/x/deep-context")).toBe(false);
  });

  it("defaults desk strict on", () => {
    expect(deskStrictEnabled(undefined)).toBe(true);
    expect(deskStrictEnabled("false")).toBe(false);
    expect(deskStrictEnabled("true")).toBe(true);
  });

  it("blocks auto mocks on desk paths when strict", () => {
    const desk = "/api/cases/v1/cases/ops/kpis?tenant_id=demo";
    expect(
      mocksAllowedForUrl(desk, { useApiMocks: true, mockMode: "auto", deskStrict: true }),
    ).toBe(false);
    expect(
      mocksAllowedForUrl(desk, { useApiMocks: true, mockMode: "true", deskStrict: true }),
    ).toBe(true);
    expect(
      mocksAllowedForUrl("/api/graph/v1/health", {
        useApiMocks: true,
        mockMode: "auto",
        deskStrict: true,
      }),
    ).toBe(true);
  });
});
