import { describe, expect, it } from "vitest";
import {
  deskStrictEnabled,
  isDeskApiPath,
  isUpstreamUnavailableBody,
  mocksAllowedForUrl,
} from "./deskMockPolicy";

describe("deskMockPolicy", () => {
  it("identifies desk API paths", () => {
    expect(isDeskApiPath("/api/cases/v1/cases/ops/kpis?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/cases/v1/cases/ops/qa-metrics?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/decisions/v1/ops/calibration-status?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/decisions/v1/calibration/reliability-bins")).toBe(true);
    expect(isDeskApiPath("/api/decisions/v1/ops/trend/posture?tenant_id=t")).toBe(true);
    expect(isDeskApiPath("/api/decisions/v1/ops/trend/tick")).toBe(true);
    expect(isDeskApiPath("/api/graph/v1/entities/x/deep-context")).toBe(true);
    expect(isDeskApiPath("/api/analytics/v1/health")).toBe(true);
    expect(isDeskApiPath("/api/orchestrator/v1/health")).toBe(true);
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
      mocksAllowedForUrl("/api/decisions/v1/ops/trend/drafts?tenant_id=t", {
        useApiMocks: true,
        mockMode: "auto",
        deskStrict: true,
      }),
    ).toBe(false);
    expect(
      mocksAllowedForUrl("/api/graph/v1/health", {
        useApiMocks: true,
        mockMode: "auto",
        deskStrict: true,
      }),
    ).toBe(false);
  });

  it("treats nginx upstream_unavailable as not mockable", () => {
    expect(isUpstreamUnavailableBody('{"error":"upstream_unavailable"}')).toBe(true);
    expect(isUpstreamUnavailableBody("<html>ok</html>")).toBe(false);
  });
});
