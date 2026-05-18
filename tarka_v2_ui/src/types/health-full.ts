export type HealthServiceKey = "orchestrator" | "rule_engine" | "shadow_ai";

export type HealthServiceSnapshot = {
  online: boolean;
  /** Round-trip probe latency when online; may be last attempt RTT when offline. */
  latency_ms: number | null;
  /** Human-readable failure (e.g. `503 Service Unavailable`). */
  error_message: string | null;
};

export type HealthFullResponse = {
  orchestrator: HealthServiceSnapshot;
  rule_engine: HealthServiceSnapshot;
  shadow_ai: HealthServiceSnapshot;
};
