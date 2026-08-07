/** Client-side L3 arm guards — mirror decision_api.l3_ops_ledger.arm_ledger. */

const BANNED_TENANTS = new Set(["demo", "demo-tenant", "fixture", "sim", "test"]);

export function isBannedL3Tenant(tenantId: string): boolean {
  const tid = (tenantId || "").trim().toLowerCase();
  return !tid || BANNED_TENANTS.has(tid);
}

export function isBannedL3Sink(sink: string): boolean {
  const s = (sink || "").trim().toLowerCase();
  return !s || s.startsWith("sim:") || s.includes("shadow_four_week_sim");
}

export function validateL3ArmInput(input: {
  tenant_id: string;
  week1_start_utc: string;
  host_action_sink: string;
  shadow_evaluate_enabled: boolean;
}): string[] {
  const blockers: string[] = [];
  if (isBannedL3Tenant(input.tenant_id)) {
    blockers.push("tenant_id_must_be_named_live_tenant");
  }
  if (isBannedL3Sink(input.host_action_sink)) {
    blockers.push(
      input.host_action_sink.trim().toLowerCase().startsWith("sim:") ||
        input.host_action_sink.toLowerCase().includes("shadow_four_week_sim")
        ? "host_action_sink_cannot_be_sim"
        : "host_action_sink_required",
    );
  }
  if (!/^\d{4}-\d{2}-\d{2}/.test((input.week1_start_utc || "").trim())) {
    blockers.push("week1_start_utc_invalid");
  }
  if (!input.shadow_evaluate_enabled) {
    blockers.push("shadow_evaluate_must_be_enabled");
  }
  return blockers;
}
