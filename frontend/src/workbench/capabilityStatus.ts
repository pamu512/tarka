/** Map workbench fetch outcomes to operator-visible capability chips. */

export type CapabilityState = "ok" | "down" | "missing";

export type CapabilityStatus = {
  audit: CapabilityState;
  graph: CapabilityState;
  calibration: CapabilityState;
};

export function auditCapability(hasTrace: boolean, fetchOk: boolean | null): CapabilityState {
  if (!hasTrace) return "missing";
  if (fetchOk === null) return "missing";
  return fetchOk ? "ok" : "down";
}

export function graphCapability(fetchOk: boolean | null): CapabilityState {
  if (fetchOk === null) return "missing";
  return fetchOk ? "ok" : "down";
}

export function calibrationCapability(fetchOk: boolean | null, _healthy: boolean | null): CapabilityState {
  if (fetchOk === null) return "missing";
  if (!fetchOk) return "down";
  // Reachable even when posture unhealthy — hint + warnings carry trust signal.
  return "ok";
}

export function initialCapabilityStatus(): CapabilityStatus {
  return { audit: "missing", graph: "missing", calibration: "missing" };
}

/** Amber warnings when a capability is down (not missing/n/a). */
export function capabilityDownWarnings(status: CapabilityStatus): string[] {
  const out: string[] = [];
  if (status.audit === "down") out.push("Decision audit unavailable — explain panels may be empty");
  if (status.graph === "down") out.push("Graph risk unavailable — topology signals cannot be trusted this session");
  if (status.calibration === "down") out.push("Calibration posture unavailable — do not treat scores as calibrated");
  return out;
}

/** Extra trust warning when calibration API is up but posture is not healthy. */
export function calibrationPostureWarnings(
  calibrationState: CapabilityState,
  calibrationHint: string | null,
): string[] {
  if (calibrationState !== "ok") return [];
  const hint = (calibrationHint || "").trim();
  if (!hint || hint === "healthy") return [];
  return [`Calibration posture not healthy — ${hint}`];
}
