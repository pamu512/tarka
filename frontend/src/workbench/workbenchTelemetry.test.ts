import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearWorkbenchTelemetryBuffer,
  getWorkbenchTelemetryBuffer,
  setWorkbenchTelemetrySink,
  trackPanelUsage,
  trackWorkbenchTask,
} from "./workbenchTelemetry";

describe("workbenchTelemetry", () => {
  beforeEach(() => {
    clearWorkbenchTelemetryBuffer();
    setWorkbenchTelemetrySink(null);
    sessionStorage.clear();
  });

  it("records panel open/close events", () => {
    trackPanelUsage("graph", true, { caseId: "c1", tenantId: "demo" });
    trackPanelUsage("graph", false, { caseId: "c1", tenantId: "demo" });
    const buf = getWorkbenchTelemetryBuffer();
    expect(buf.some((e) => e.kind === "panel_open" && e.panel === "graph")).toBe(true);
    expect(buf.some((e) => e.kind === "panel_close")).toBe(true);
  });

  it("records task completion", () => {
    trackWorkbenchTask("case_status_update", { caseId: "c1", tenantId: "demo", detail: "closed" });
    expect(getWorkbenchTelemetryBuffer().some((e) => e.kind === "task_complete" && e.task === "case_status_update")).toBe(
      true,
    );
  });

  it("forwards to optional sink", () => {
    const sink = vi.fn();
    setWorkbenchTelemetrySink(sink);
    trackPanelUsage("audit", true);
    expect(sink).toHaveBeenCalledWith(expect.objectContaining({ kind: "panel_open", panel: "audit" }));
  });
});
