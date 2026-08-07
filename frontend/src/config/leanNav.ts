/**
 * Production default: lean analyst surface (desk core).
 * Sales / full brochure demo: build with `VITE_LEAN_NAV=false`.
 *
 * - Production image (frontend/Dockerfile): `ARG VITE_LEAN_NAV=true` — brochure
 *   routes are not registered; deep links redirect to `/cases`.
 * - Demo: `docker compose … --build-arg VITE_LEAN_NAV=false` or merge
 *   `infra/deploy/docker-compose.demo-vertical.yml` (sets the build arg).
 */
export const INCLUDE_DEMO_SURFACE =
  ((import.meta.env.VITE_LEAN_NAV as string | undefined) ?? "true").trim().toLowerCase() ===
  "false";

/** Inverse of INCLUDE_DEMO_SURFACE — default on. */
export const LEAN_NAV = !INCLUDE_DEMO_SURFACE;

/**
 * Paths kept when LEAN_NAV is on — desk core only (critical regrade flag #8).
 * Simulation / shadow / investigation* / brochure ops stay behind VITE_LEAN_NAV=false.
 */
export const LEAN_NAV_PATHS = new Set<string>([
  "/cases",
  "/disputes",
  "/graph",
  "/rules",
  "/analytics/rule-performance",
  "/ops/calibration",
  "/ops/qa",
  "/ops/shadow",
  "/ops/counters",
  "/ops/sar-transport",
  "/settings",
  "/help",
]);

export function leanHomePath(): string {
  return LEAN_NAV ? "/cases" : "/command-center";
}

/** True when this path is part of the production lean surface (or a case/dispute deep link). */
export function isProductionSurfacePath(path: string): boolean {
  if (LEAN_NAV_PATHS.has(path)) return true;
  if (path === "/403-unauthorized") return true;
  if (path.startsWith("/cases/")) return true;
  if (path.startsWith("/disputes/")) return true;
  return false;
}
