/**
 * Resolves the Orchestrator audit stream URL.
 * When `NEXT_PUBLIC_ORCHESTRATOR_BASE_URL` is unset, the UI uses the local mock route.
 */
export function getAuditRecentUrl(): string {
  const base =
    typeof process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL === "string"
      ? process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL.replace(/\/$/, "")
      : "";

  if (base.length > 0) {
    return `${base}/v1/audit/recent`;
  }

  return "/api/v1/audit/recent";
}
