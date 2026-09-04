import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function loadLeanNav() {
  return import("./leanNav");
}

describe("leanNav", () => {
  it("defaults to lean home /graph when graph URL is set", async () => {
    vi.stubEnv("VITE_LEAN_NAV", undefined);
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "http://graph-service:8001");
    vi.resetModules();
    const { LEAN_NAV, INCLUDE_DEMO_SURFACE, leanHomePath } = await loadLeanNav();
    expect(LEAN_NAV).toBe(true);
    expect(INCLUDE_DEMO_SURFACE).toBe(false);
    expect(leanHomePath()).toBe("/graph");
    expect(leanHomePath()).not.toBe("/decisions");
    expect(leanHomePath()).not.toBe("/cases");
  });

  it("falls back to /decisions when graph URL is empty", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "");
    vi.resetModules();
    const { leanHomePath, isPlaneEnabled } = await loadLeanNav();
    expect(isPlaneEnabled("graph")).toBe(false);
    expect(leanHomePath()).toBe("/decisions");
  });

  it("uses demo home /command-center when VITE_LEAN_NAV=false", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "false");
    vi.resetModules();
    const { LEAN_NAV, INCLUDE_DEMO_SURFACE, leanHomePath } = await loadLeanNav();
    expect(LEAN_NAV).toBe(false);
    expect(INCLUDE_DEMO_SURFACE).toBe(true);
    expect(leanHomePath()).toBe("/command-center");
  });

  it("keeps desk core paths and excludes brochure simulation", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.resetModules();
    const { isProductionSurfacePath, LEAN_NAV_PATHS } = await loadLeanNav();
    expect(isProductionSurfacePath("/cases")).toBe(true);
    expect(isProductionSurfacePath("/leftovers")).toBe(true);
    expect(isProductionSurfacePath("/cases/abc")).toBe(true);
    expect(isProductionSurfacePath("/ops/qa")).toBe(true);
    expect(isProductionSurfacePath("/ops/calibration")).toBe(true);
    expect(isProductionSurfacePath("/ops/shadow")).toBe(true);
    expect(isProductionSurfacePath("/disputes/x")).toBe(true);
    expect(isProductionSurfacePath("/decisions")).toBe(true);
    expect(isProductionSurfacePath("/decisions/tr-abc")).toBe(true);
    expect(isProductionSurfacePath("/analytics/promo-abuse")).toBe(false);
    expect(isProductionSurfacePath("/integrations/seller-integrity")).toBe(false);
    expect(isProductionSurfacePath("/integrations/payout-delay")).toBe(false);
    expect(isProductionSurfacePath("/403-unauthorized")).toBe(true);
    expect(isProductionSurfacePath("/login")).toBe(true);
    expect(isProductionSurfacePath("/auth/callback")).toBe(true);
    expect(LEAN_NAV_PATHS.has("/ops/shadow")).toBe(true);
    expect(LEAN_NAV_PATHS.has("/decisions")).toBe(true);
    expect(LEAN_NAV_PATHS.has("/analytics/promo-abuse")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/integrations/seller-integrity")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/integrations/payout-delay")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/simulation")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/shadow")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/observe")).toBe(true);
    expect(LEAN_NAV_PATHS.has("/investigation/shadow-llm")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/investigation")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/admin")).toBe(false);
    expect(isProductionSurfacePath("/command-center")).toBe(false);
    expect(isProductionSurfacePath("/simulation")).toBe(false);
    expect(isProductionSurfacePath("/shadow")).toBe(false);
    expect(isProductionSurfacePath("/observe")).toBe(true);
  });

  it("treats empty plane URLs as off and hides Graph / Advise / signal chrome", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "");
    vi.stubEnv("VITE_INVESTIGATION_AGENT_URL", "  ");
    vi.stubEnv("VITE_SIGNAL_API_URL", undefined);
    vi.resetModules();
    const {
      isPlaneEnabled,
      isNavItemVisible,
      isProductionSurfacePath,
      visibleLeanNavPaths,
      planeForPath,
    } = await loadLeanNav();
    expect(isPlaneEnabled("graph")).toBe(false);
    expect(isPlaneEnabled("advise")).toBe(false);
    expect(isPlaneEnabled("signals")).toBe(false);
    expect(planeForPath("/graph")).toBe("graph");
    expect(planeForPath("/graph/mule-path")).toBe("graph");
    expect(planeForPath("/investigation/shadow-llm")).toBe("advise");
    expect(isNavItemVisible("/graph")).toBe(false);
    expect(isNavItemVisible("/leftovers")).toBe(false);
    expect(isNavItemVisible("/investigation/shadow-llm")).toBe(false);
    expect(isNavItemVisible("/ops/calibration")).toBe(false);
    expect(isNavItemVisible("/ops/counters")).toBe(false);
    expect(isNavItemVisible("/decisions")).toBe(true);
    expect(isNavItemVisible("/rules")).toBe(true);
    expect(isNavItemVisible("/cases")).toBe(false);
    expect(isProductionSurfacePath("/cases")).toBe(true);
    expect(visibleLeanNavPaths()).not.toContain("/graph");
    expect(visibleLeanNavPaths()).not.toContain("/cases");
    expect(visibleLeanNavPaths()).toContain("/decisions");
    expect(visibleLeanNavPaths()).toContain("/rules");
  });

  it("shows /ops/shadow when VITE_SIGNAL_API_URL is empty", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.stubEnv("VITE_SIGNAL_API_URL", "");
    vi.resetModules();
    const { isNavItemVisible, planeForPath } = await loadLeanNav();
    expect(isNavItemVisible("/ops/shadow")).toBe(true);
    expect(planeForPath("/ops/shadow")).toBe(null);
    expect(planeForPath("/ops/shadow")).not.toBe("signals");
  });

  it("shows Observe pack promote (/observe) on the lean desk", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.resetModules();
    const { isNavItemVisible, isProductionSurfacePath, LEAN_NAV_PATHS } = await loadLeanNav();
    expect(LEAN_NAV_PATHS.has("/observe")).toBe(true);
    expect(LEAN_NAV_PATHS.has("/shadow")).toBe(false);
    expect(isProductionSurfacePath("/observe")).toBe(true);
    expect(isNavItemVisible("/observe")).toBe(true);
  });

  it("shows Graph / Advise / signal chrome when plane URLs are set", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "http://graph-service:8001");
    vi.stubEnv("VITE_INVESTIGATION_AGENT_URL", "http://investigation-agent:8006");
    vi.stubEnv("VITE_SIGNAL_API_URL", "http://signal-api:8004");
    vi.resetModules();
    const { isPlaneEnabled, isNavItemVisible } = await loadLeanNav();
    expect(isPlaneEnabled("graph")).toBe(true);
    expect(isPlaneEnabled("advise")).toBe(true);
    expect(isPlaneEnabled("signals")).toBe(true);
    expect(isNavItemVisible("/graph")).toBe(true);
    expect(isNavItemVisible("/graph/mule-path")).toBe(false);
    expect(isNavItemVisible("/leftovers")).toBe(true);
    expect(isNavItemVisible("/cases")).toBe(false);
    expect(isNavItemVisible("/ops/calibration")).toBe(true);
    expect(isNavItemVisible("/investigation")).toBe(false);
  });

  it("keeps mule path on the brochure surface when the graph plane is on", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "false");
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "http://graph-service:8001");
    vi.resetModules();
    const { isNavItemVisible, INCLUDE_DEMO_SURFACE } = await loadLeanNav();
    expect(INCLUDE_DEMO_SURFACE).toBe(true);
    expect(isNavItemVisible("/graph/mule-path")).toBe(true);
  });

  it("hides Graph on the brochure surface when the graph URL is empty", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "false");
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "");
    vi.resetModules();
    const { isNavItemVisible, INCLUDE_DEMO_SURFACE } = await loadLeanNav();
    expect(INCLUDE_DEMO_SURFACE).toBe(true);
    expect(isNavItemVisible("/graph")).toBe(false);
    expect(isNavItemVisible("/graph/mule-path")).toBe(false);
    expect(isNavItemVisible("/command-center")).toBe(true);
  });
});
