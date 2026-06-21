import { describe, expect, it } from "vitest";
import {
  CASE_WORKBENCH_TABS,
  DEFAULT_WORKBENCH_PANELS,
  isCaseWorkbenchTab,
  normalizeWorkbenchComposition,
  WORKBENCH_PANEL_IDS,
} from "./workbenchContract";

describe("workbenchContract", () => {
  it("defines core panel ids", () => {
    expect(WORKBENCH_PANEL_IDS).toContain("copilot_rail");
    expect(WORKBENCH_PANEL_IDS).toContain("path_reasoning");
    expect(WORKBENCH_PANEL_IDS).toContain("bridge_confirm");
  });

  it("validates case tabs", () => {
    expect(isCaseWorkbenchTab("audit")).toBe(true);
    expect(isCaseWorkbenchTab("nope")).toBe(false);
    expect(CASE_WORKBENCH_TABS).toEqual(["timeline", "audit", "graph"]);
  });

  it("normalizes stored composition", () => {
    const raw = {
      version: 1,
      panels: { ...DEFAULT_WORKBENCH_PANELS, path_reasoning: false },
      activeTab: "graph",
      copilotRailOpen: false,
    };
    const got = normalizeWorkbenchComposition(raw);
    expect(got?.panels.path_reasoning).toBe(false);
    expect(got?.activeTab).toBe("graph");
    expect(got?.copilotRailOpen).toBe(false);
  });
});
