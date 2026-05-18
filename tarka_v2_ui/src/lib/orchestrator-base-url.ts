/**
 * Orchestrator HTTP origin for BFF routes (server-side env preferred).
 */
export function getOrchestratorBaseUrl(): string {
  const raw =
    (typeof process.env.TARKA_ORCHESTRATOR_BASE === "string"
      ? process.env.TARKA_ORCHESTRATOR_BASE
      : null) ??
    (typeof process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL === "string"
      ? process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL
      : null) ??
    "";
  return raw.replace(/\/$/, "");
}
