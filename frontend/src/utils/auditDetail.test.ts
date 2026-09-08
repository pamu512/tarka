import { describe, expect, it, vi } from "vitest";

import { ApiRequestError, type AuditEntry } from "../api/client";
import { getAuditForPackWhy, isAuditDetailForbidden } from "./auditDetail";

const MINIMAL: AuditEntry = {
  trace_id: "tr-1",
  entity_id: "ent-1",
  tenant_id: "demo",
  event_type: "login",
  decision: "review",
  score: 62,
  tags: [],
  rule_hits: ["sdk_rooted"],
  rule_pack_file: "device_signals.json",
  created_at: "2026-08-24T08:00:00Z",
};

describe("getAuditForPackWhy", () => {
  it("retries minimal after analyst 403 and returns the real payload", async () => {
    const getAudit = vi.fn(async (_tid: string, _tenant: string, opts?: { detail_level?: string }) => {
      if (opts?.detail_level === "analyst") {
        throw new ApiRequestError("403 analyst role required for full audit detail", { status: 403 });
      }
      return MINIMAL;
    });

    const row = await getAuditForPackWhy(getAudit, "tr-1", "demo");

    expect(row.rule_hits).toEqual(["sdk_rooted"]);
    expect(row.rule_pack_file).toBe("device_signals.json");
    expect(getAudit).toHaveBeenNthCalledWith(1, "tr-1", "demo", { detail_level: "analyst" });
    expect(getAudit).toHaveBeenNthCalledWith(2, "tr-1", "demo", { detail_level: "minimal" });
  });

  it("does not retry minimal on non-403 analyst failures", async () => {
    const getAudit = vi.fn(async () => {
      throw new ApiRequestError("500 upstream", { status: 500 });
    });

    await expect(getAuditForPackWhy(getAudit, "tr-1", "demo")).rejects.toMatchObject({ status: 500 });
    expect(getAudit).toHaveBeenCalledTimes(1);
  });

  it("throws the minimal failure when both tiers fail", async () => {
    const getAudit = vi.fn(async (_tid: string, _tenant: string, opts?: { detail_level?: string }) => {
      throw new ApiRequestError(
        opts?.detail_level === "minimal" ? "403 still forbidden" : "403 analyst role required",
        { status: 403 },
      );
    });

    await expect(getAuditForPackWhy(getAudit, "tr-1", "demo")).rejects.toMatchObject({
      message: "403 still forbidden",
    });
    expect(getAudit).toHaveBeenCalledTimes(2);
  });

  it("treats ApiRequestError 403 and 403-prefixed messages as forbidden", () => {
    expect(isAuditDetailForbidden(new ApiRequestError("analyst role required", { status: 403 }))).toBe(true);
    expect(isAuditDetailForbidden(new Error("403 analyst role required for full audit detail"))).toBe(true);
    expect(isAuditDetailForbidden(new Error("500 boom"))).toBe(false);
    expect(isAuditDetailForbidden(new ApiRequestError("403 confusing", { status: 500 }))).toBe(false);
  });
});
