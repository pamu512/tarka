/** Q2-E01 unified analyst workbench composition contract. */

export const WORKBENCH_PANEL_IDS = [
  "header",
  "graph",
  "audit",
  "copilot_rail",
  "pins",
  "path_reasoning",
  "hil_overrides",
  "benchmark_drift",
  "counters",
  "bridge_confirm",
] as const;

export type WorkbenchPanelId = (typeof WORKBENCH_PANEL_IDS)[number];

export type CaseWorkbenchTab = "timeline" | "audit" | "graph";

export const CASE_WORKBENCH_TABS: readonly CaseWorkbenchTab[] = ["timeline", "audit", "graph"];

export function isCaseWorkbenchTab(v: string | null): v is CaseWorkbenchTab {
  return v != null && (CASE_WORKBENCH_TABS as readonly string[]).includes(v);
}

/** Default snap-in panel visibility for a fresh case session. */
export const DEFAULT_WORKBENCH_PANELS: Record<WorkbenchPanelId, boolean> = {
  header: true,
  graph: true,
  audit: true,
  copilot_rail: false,
  pins: true,
  path_reasoning: false,
  hil_overrides: false,
  benchmark_drift: false,
  counters: true,
  bridge_confirm: true,
};

export type WorkbenchComposition = {
  version: 1;
  panels: Record<WorkbenchPanelId, boolean>;
  activeTab: CaseWorkbenchTab;
  copilotRailOpen: boolean;
};

export const WORKBENCH_COMPOSITION_VERSION = 1 as const;

export function normalizeWorkbenchComposition(raw: unknown): WorkbenchComposition | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (o.version !== WORKBENCH_COMPOSITION_VERSION) return null;
  const panelsRaw = o.panels;
  if (!panelsRaw || typeof panelsRaw !== "object") return null;
  const panels = { ...DEFAULT_WORKBENCH_PANELS };
  for (const id of WORKBENCH_PANEL_IDS) {
    const v = (panelsRaw as Record<string, unknown>)[id];
    if (typeof v === "boolean") panels[id] = v;
  }
  const tab = typeof o.activeTab === "string" && isCaseWorkbenchTab(o.activeTab) ? o.activeTab : "timeline";
  const copilotRailOpen = typeof o.copilotRailOpen === "boolean" ? o.copilotRailOpen : false;
  return { version: WORKBENCH_COMPOSITION_VERSION, panels, activeTab: tab, copilotRailOpen };
}
