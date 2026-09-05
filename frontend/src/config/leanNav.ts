/**
 * Production default: product analyst surface (visual / backtest / lists).
 * Demo skin (first-hour pages): `VITE_DESK_PROFILE=demo` or legacy `VITE_LEAN_NAV=true`.
 * Sales / full brochure: `VITE_DESK_PROFILE=brochure` or `VITE_LEAN_NAV=false`.
 *
 * Empty Advise / signals URL = plane off (modular). Graph is required for the
 * desk: Tarka AGE (lite) or a graph the operator wires in. Empty
 * VITE_GRAPH_SERVICE_URL is not the product default — home falls back to
 * /decisions and Hunt is hidden.
 *
 * - Production image (frontend/Dockerfile): `ARG VITE_DESK_PROFILE=product`.
 * - Demo compose (fraud-desk): `VITE_DESK_PROFILE=demo`.
 * - Brochure overlay: `VITE_DESK_PROFILE=brochure` or merge
 *   `infra/deploy/docker-compose.demo-vertical.yml`.
 */
import { resolveDeskProfile, type DeskProfile } from "./deskProfile";

export const DESK_PROFILE: DeskProfile = resolveDeskProfile();
export const INCLUDE_DEMO_SURFACE = DESK_PROFILE === "brochure";
export const LEAN_NAV = DESK_PROFILE === "demo";

export type PlaneId = "graph" | "advise" | "signals";

function envUrlOn(raw: string | undefined): boolean {
  return Boolean(raw?.trim());
}

/** Empty / absent URL means the plane is not deployed. */
export function isPlaneEnabled(plane: PlaneId): boolean {
  switch (plane) {
    case "graph":
      return envUrlOn(import.meta.env.VITE_GRAPH_SERVICE_URL as string | undefined);
    case "advise":
      return envUrlOn(import.meta.env.VITE_INVESTIGATION_AGENT_URL as string | undefined);
    case "signals":
      return envUrlOn(import.meta.env.VITE_SIGNAL_API_URL as string | undefined);
    default: {
      const _exhaustive: never = plane;
      return _exhaustive;
    }
  }
}

const EXACT_PATH_PLANE: Record<string, PlaneId> = {
  "/graph": "graph",
  "/graph/mule-path": "graph",
  "/graph/link-analysis": "graph",
  "/investigation": "advise",
  "/investigation/dag-trace": "advise",
  "/investigation/shadow-llm": "advise",
  "/ops/calibration": "signals",
  "/ops/counters": "signals",
};

export function planeForPath(path: string): PlaneId | null {
  const exact = EXACT_PATH_PLANE[path];
  if (exact) return exact;
  if (path.startsWith("/graph/") || path === "/graph") return "graph";
  if (path.startsWith("/investigation/") || path === "/investigation") return "advise";
  return null;
}

/**
 * Paths kept when LEAN_NAV is on — evaluate + residual cases + ops that live on core-api.
 * Graph / Advise / signal-api chrome are in this set so deep links can render an
 * honest "plane off" page; `isNavItemVisible` hides them from the sidebar when
 * the plane URL is empty. Simulation / brochure ops stay behind
 * VITE_LEAN_NAV=false. Observe pack modes live at `/observe` (not brochure
 * `/shadow` — audit_prod_desk_mocks forbids that path on lean).
 */
export const LEAN_NAV_PATHS = new Set<string>([
  "/cases",
  "/leftovers",
  "/decisions",
  "/disputes",
  "/graph",
  "/rules",
  "/observe",
  "/analytics/rule-performance",
  "/ops/calibration",
  "/ops/qa",
  "/ops/shadow",
  "/ops/dispute-deadlines",
  "/ops/counters",
  "/ops/sar-transport",
  "/settings",
  "/notifications",
  "/help",
]);

export const PRODUCT_JOB_PATHS = new Set<string>([
  ...LEAN_NAV_PATHS,
  "/rules/visual",
  "/ops/backtest",
  "/entity-lists",
  "/simulation",
  "/analytics",
]);

/** Hunt when graph is wired. Receipts only if graph URL is empty. */
export function leanHomePath(): string {
  if (DESK_PROFILE === "brochure") return "/command-center";
  return isPlaneEnabled("graph") ? "/graph" : "/decisions";
}

/** True when this path is part of the production lean surface (or a case/dispute deep link). */
export function isProductionSurfacePath(path: string): boolean {
  if (DESK_PROFILE === "product" && PRODUCT_JOB_PATHS.has(path)) return true;
  if (LEAN_NAV_PATHS.has(path)) return true;
  if (path === "/403-unauthorized") return true;
  if (path === "/login" || path === "/auth/callback") return true;
  if (path.startsWith("/cases/")) return true;
  if (path.startsWith("/disputes/")) return true;
  if (path === "/decisions" || path.startsWith("/decisions/")) return true;
  if (path === "/graph" || path.startsWith("/graph/")) return true;
  if (DESK_PROFILE === "product" && path.startsWith("/rules/")) return true;
  return false;
}

/** Sidebar / command-palette visibility. Empty plane URL hides the item (no "coming soon"). */
export function isNavItemVisible(path: string): boolean {
  if (DESK_PROFILE === "demo" && !isProductionSurfacePath(path)) return false;
  if (DESK_PROFILE === "product" && !PRODUCT_JOB_PATHS.has(path) && !isProductionSurfacePath(path)) {
    return false;
  }
  if ((DESK_PROFILE === "demo" || DESK_PROFILE === "product") && path === "/cases") return false;
  if (path === "/leftovers" && !isPlaneEnabled("graph")) return false;
  if ((DESK_PROFILE === "demo" || DESK_PROFILE === "product") && path === "/graph/mule-path") return false;
  const plane = planeForPath(path);
  if (plane && !isPlaneEnabled(plane)) return false;
  return true;
}

/** Desk help list: production paths that are actually on this build. */
export function visibleDeskNavPaths(): string[] {
  const set = DESK_PROFILE === "product" ? PRODUCT_JOB_PATHS : LEAN_NAV_PATHS;
  return [...set].filter((path) => isNavItemVisible(path)).sort();
}

export const visibleLeanNavPaths = visibleDeskNavPaths;
