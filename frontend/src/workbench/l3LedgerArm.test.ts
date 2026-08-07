import { describe, expect, it } from "vitest";
import { isBannedL3Tenant, validateL3ArmInput } from "./l3LedgerArm";

describe("l3LedgerArm", () => {
  it("rejects demo/sim tenants", () => {
    expect(isBannedL3Tenant("demo")).toBe(true);
    expect(isBannedL3Tenant("acme-prod")).toBe(false);
  });

  it("validateL3ArmInput fail-closed on demo + sim sink", () => {
    const blockers = validateL3ArmInput({
      tenant_id: "demo",
      week1_start_utc: "2026-08-07",
      host_action_sink: "sim:shadow_four_week_sim",
      shadow_evaluate_enabled: true,
    });
    expect(blockers).toContain("tenant_id_must_be_named_live_tenant");
    expect(blockers).toContain("host_action_sink_cannot_be_sim");
  });

  it("allows named tenant + internal sink", () => {
    expect(
      validateL3ArmInput({
        tenant_id: "acme-prod",
        week1_start_utc: "2026-08-07",
        host_action_sink: "internal:jsonl:/tmp/host.jsonl",
        shadow_evaluate_enabled: true,
      }),
    ).toEqual([]);
  });
});
