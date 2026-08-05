/**
 * Production default: lean analyst surface (triad + cases).
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

/** Paths kept in sidebar / command palette / route table when LEAN_NAV is on. */
export const LEAN_NAV_PATHS = new Set<string>([
  "/dashboard",
  "/cases",
  "/disputes",
  "/graph",
  "/graph/link-analysis",
  "/investigation",
  "/investigation/dag-trace",
  "/investigation/shadow-llm",
  "/analytics",
  "/analytics/rule-performance",
  "/analytics/audit-log",
  "/transactions/live",
  "/rules",
  "/rules/visual",
  "/entity-lists",
  "/shadow",
  "/simulation",
  "/ops/backtest",
  "/compliance",
  "/ops/calibration",
  "/ops/qa",
  "/ops/integrity",
  "/ops/counters",
  "/ops/features",
  "/ops/pipelines",
  "/ops/sar-transport",
  "/ops/infra",
  "/integrations",
  "/settings",
  "/help",
  "/admin",
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
