import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function loadLeanNav() {
  return import("./leanNav");
}

describe("leanNav", () => {
  it("defaults to lean home /cases when VITE_LEAN_NAV is unset", async () => {
    vi.stubEnv("VITE_LEAN_NAV", undefined);
    vi.resetModules();
    const { LEAN_NAV, INCLUDE_DEMO_SURFACE, leanHomePath } = await loadLeanNav();
    expect(LEAN_NAV).toBe(true);
    expect(INCLUDE_DEMO_SURFACE).toBe(false);
    expect(leanHomePath()).toBe("/cases");
  });

  it("uses demo home /command-center when VITE_LEAN_NAV=false", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "false");
    vi.resetModules();
    const { LEAN_NAV, INCLUDE_DEMO_SURFACE, leanHomePath } = await loadLeanNav();
    expect(LEAN_NAV).toBe(false);
    expect(INCLUDE_DEMO_SURFACE).toBe(true);
    expect(leanHomePath()).toBe("/command-center");
  });

  it("keeps desk core paths and excludes brochure simulation/shadow", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.resetModules();
    const { isProductionSurfacePath, LEAN_NAV_PATHS } = await loadLeanNav();
    expect(isProductionSurfacePath("/cases")).toBe(true);
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
    expect(LEAN_NAV_PATHS.has("/investigation")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/admin")).toBe(false);
    expect(isProductionSurfacePath("/command-center")).toBe(false);
    expect(isProductionSurfacePath("/simulation")).toBe(false);
    expect(isProductionSurfacePath("/shadow")).toBe(false);
  });
});
