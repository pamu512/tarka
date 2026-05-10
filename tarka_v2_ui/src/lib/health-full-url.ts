/**
 * Resolves GET /health/full on the orchestrator (or local mock on the app origin).
 */
export function getHealthFullUrl(): string {
  const base =
    typeof process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL === "string"
      ? process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL.replace(/\/$/, "")
      : "";

  if (base.length > 0) {
    return `${base}/health/full`;
  }

  return "/health/full";
}
