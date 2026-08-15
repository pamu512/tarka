/**
 * Desk-strict mock policy (missed-mark bridge Track A1).
 * Lean desk routes (cases, calibration, QA, trend, graph, analytics,
 * orchestrator, ingest) must not silently fall back to mockData unless mocks
 * are explicitly forced with VITE_USE_API_MOCKS=true.
 */

export function isDeskApiPath(url: string): boolean {
  const path = url.split("?")[0] ?? url;
  return (
    path.includes("/api/cases/") ||
    path.includes("/api/decisions/v1/ops/calibration") ||
    path.includes("/api/decisions/v1/calibration") ||
    path.includes("/api/decisions/v1/ops/qa") ||
    path.includes("/api/decisions/v1/ops/trend") ||
    path.includes("/cases/ops/qa") ||
    path.includes("/api/graph") ||
    path.includes("/api/analytics") ||
    path.includes("/api/orchestrator") ||
    path.includes("/api/ingest")
  );
}

export function isUpstreamUnavailableBody(text: string): boolean {
  const raw = text.trim();
  if (!raw.startsWith("{")) return false;
  try {
    const parsed = JSON.parse(raw) as { error?: unknown };
    return parsed.error === "upstream_unavailable";
  } catch {
    return false;
  }
}

export function deskStrictEnabled(raw: string | undefined): boolean {
  // Default ON — set VITE_DESK_STRICT=false to restore auto mock fallback on desk routes.
  return (raw ?? "true").trim().toLowerCase() !== "false";
}

/**
 * @param useApiMocks - result of global USE_API_MOCKS (non-prod + mode)
 * @param mockMode - raw VITE_USE_API_MOCKS (auto|true|false)
 * @param deskStrict - VITE_DESK_STRICT parsed
 */
export function mocksAllowedForUrl(
  url: string,
  opts: { useApiMocks: boolean; mockMode: string; deskStrict: boolean },
): boolean {
  if (!opts.useApiMocks) return false;
  if (opts.deskStrict && isDeskApiPath(url)) {
    return opts.mockMode === "true";
  }
  return true;
}
