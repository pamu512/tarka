/**
 * Production default: lean analyst surface (evaluate-only / thin desk).
 * Sales / full brochure demo: build with `VITE_LEAN_NAV=false`.
 *
 * Empty Advise / signals URL = plane off (modular). Graph is required for the
 * desk: Tarka AGE (lite) or a graph the operator wires in. Empty
 * VITE_GRAPH_SERVICE_URL is not the product default — home falls back to
 * /decisions and Hunt is hidden.
 *
 * - Production image (frontend/Dockerfile): `ARG VITE_LEAN_NAV=true` — brochure
 *   routes are not registered; deep links to unknown paths redirect to home.
 * - Demo: `docker compose … --build-arg VITE_LEAN_NAV=false` or merge
 *   `infra/deploy/docker-compose.demo-vertical.yml` (sets the build arg).
 */
export const INCLUDE_DEMO_SURFACE =
  ((import.meta.env.VITE_LEAN_NAV as string | undefined) ?? "true").trim().toLowerCase() ===
  "false";

/** Inverse of INCLUDE_DEMO_SURFACE — default on. */
export const LEAN_NAV = !INCLUDE_DEMO_SURFACE;

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
 * the plane URL is empty. Simulation / Observe / brochure ops stay behind
 * VITE_LEAN_NAV=false.
 */
export const LEAN_NAV_PATHS = new Set<string>([
  "/cases",
  "/leftovers",
  "/decisions",
  "/disputes",
  "/graph",
  "/rules",
  "/analytics/rule-performance",
  "/ops/calibration",
  "/ops/qa",
  "/ops/shadow",
  "/ops/dispute-deadlines",
  "/ops/counters",
  "/ops/sar-transport",
  "/settings",
  "/help",
]);

/** Hunt when graph is wired. Receipts only if graph URL is empty. */
export function leanHomePath(): string {
  if (!LEAN_NAV) return "/command-center";
  return isPlaneEnabled("graph") ? "/graph" : "/decisions";
}

/** True when this path is part of the production lean surface (or a case/dispute deep link). */
export function isProductionSurfacePath(path: string): boolean {
  if (LEAN_NAV_PATHS.has(path)) return true;
  if (path === "/403-unauthorized") return true;
  if (path === "/login" || path === "/auth/callback") return true;
  if (path.startsWith("/cases/")) return true;
  if (path.startsWith("/disputes/")) return true;
  if (path === "/decisions" || path.startsWith("/decisions/")) return true;
  if (path === "/graph" || path.startsWith("/graph/")) return true;
  return false;
}

/** Sidebar / command-palette visibility. Empty plane URL hides the item (no "coming soon"). */
export function isNavItemVisible(path: string): boolean {
  if (LEAN_NAV && !isProductionSurfacePath(path)) return false;
  // Leftover Hold still deep-links to /cases/:id. The queue is not the job.
  if (LEAN_NAV && path === "/cases") return false;
  // Leftovers without Hunt is a ticket queue.
  if (path === "/leftovers" && !isPlaneEnabled("graph")) return false;
  // Brochure fund-flow page. Lean desk is Hunt; this route redirects to /graph.
  if (LEAN_NAV && path === "/graph/mule-path") return false;
  const plane = planeForPath(path);
  if (plane && !isPlaneEnabled(plane)) return false;
  return true;
}

/** Lean help list: production paths that are actually on this build. */
export function visibleLeanNavPaths(): string[] {
  return [...LEAN_NAV_PATHS].filter((path) => isNavItemVisible(path)).sort();
}
