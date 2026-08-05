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

  it("treats lean triad deep links as production surface paths", async () => {
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.resetModules();
    const { isProductionSurfacePath } = await loadLeanNav();
    expect(isProductionSurfacePath("/cases")).toBe(true);
    expect(isProductionSurfacePath("/cases/abc")).toBe(true);
    expect(isProductionSurfacePath("/ops/qa")).toBe(true);
    expect(isProductionSurfacePath("/ops/integrity")).toBe(true);
    expect(isProductionSurfacePath("/disputes/x")).toBe(true);
    expect(isProductionSurfacePath("/403-unauthorized")).toBe(true);
    expect(isProductionSurfacePath("/admin")).toBe(true);
    expect(isProductionSurfacePath("/command-center")).toBe(false);
    expect(isProductionSurfacePath("/notifications")).toBe(false);
  });
});
