import type { WorkbenchPanelId } from "./workbenchContract";

export type WorkbenchTelemetryEvent =
  | { kind: "panel_open"; panel: WorkbenchPanelId; caseId?: string; tenantId?: string }
  | { kind: "panel_close"; panel: WorkbenchPanelId; caseId?: string; tenantId?: string }
  | { kind: "task_complete"; task: string; caseId?: string; tenantId?: string; detail?: string }
  | { kind: "tab_change"; tab: string; caseId?: string; tenantId?: string };

type TelemetrySink = (event: WorkbenchTelemetryEvent) => void;

const STORAGE_KEY = "tarka-workbench-telemetry-v1";
const MAX_BUFFER = 200;

let sink: TelemetrySink | null = null;

/** Optional override for tests or future analytics pipeline wiring. */
export function setWorkbenchTelemetrySink(next: TelemetrySink | null) {
  sink = next;
}

function readBuffer(): WorkbenchTelemetryEvent[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as WorkbenchTelemetryEvent[]).slice(-MAX_BUFFER) : [];
  } catch {
    return [];
  }
}

function writeBuffer(events: WorkbenchTelemetryEvent[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(events.slice(-MAX_BUFFER)));
  } catch {
    /* ignore quota */
  }
}

/** Fire-and-forget panel / task telemetry (sessionStorage ring buffer + optional sink). */
export function trackWorkbenchEvent(event: WorkbenchTelemetryEvent) {
  const stamped = { ...event, at: new Date().toISOString() };
  const next = [...readBuffer(), stamped as WorkbenchTelemetryEvent & { at: string }];
  writeBuffer(next);
  sink?.(event);
  if (import.meta.env.DEV) {
    console.debug("[workbench-telemetry]", stamped);
  }
}

export function trackPanelUsage(
  panel: WorkbenchPanelId,
  open: boolean,
  ctx?: { caseId?: string; tenantId?: string },
) {
  trackWorkbenchEvent({
    kind: open ? "panel_open" : "panel_close",
    panel,
    caseId: ctx?.caseId,
    tenantId: ctx?.tenantId,
  });
}

export function trackWorkbenchTask(
  task: string,
  ctx?: { caseId?: string; tenantId?: string; detail?: string },
) {
  trackWorkbenchEvent({
    kind: "task_complete",
    task,
    caseId: ctx?.caseId,
    tenantId: ctx?.tenantId,
    detail: ctx?.detail,
  });
}

export function getWorkbenchTelemetryBuffer(): WorkbenchTelemetryEvent[] {
  return readBuffer();
}

export function clearWorkbenchTelemetryBuffer() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
