/**
 * Resolves POST /v1/demo/simulate_attack for the orchestrator (or local mock).
 */
export function getSimulateAttackUrl(): string {
  const base =
    typeof process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL === "string"
      ? process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL.replace(/\/$/, "")
      : "";

  if (base.length > 0) {
    return `${base}/v1/demo/simulate_attack`;
  }

  return "/api/v1/demo/simulate_attack";
}
