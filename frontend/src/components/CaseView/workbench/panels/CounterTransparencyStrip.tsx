import { useEffect, useMemo, useState } from "react";
import type { CounterCatalogEntry } from "../../../../api/client";
import { decisions } from "../../../../api/v1/decisions";
import { CounterTransparencyChip } from "../CopilotCitationCards";
import { useCaseWorkbench } from "../../../../context/CaseWorkbenchContext";
import { toUserFacingApiError } from "../../../../api/client";
import { trackPanelUsage } from "../../../../workbench/workbenchTelemetry";

function catalogIndex(entries: CounterCatalogEntry[]): Map<string, CounterCatalogEntry> {
  const m = new Map<string, CounterCatalogEntry>();
  for (const e of entries) {
    if (e.name) m.set(e.name, e);
  }
  return m;
}

/** E06 — counter transparency tooltips with ops deep-links. */
export function CounterTransparencyStrip() {
  const { caseId, tenantId, decisionExplain, isPanelOpen } = useCaseWorkbench();
  const [catalog, setCatalog] = useState<CounterCatalogEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const open = isPanelOpen("counters");

  useEffect(() => {
    if (!open) return;
    trackPanelUsage("counters", true, { caseId, tenantId });
    void decisions
      .counterCatalog()
      .then((c) => setCatalog(c.counters ?? []))
      .catch((e) => setErr(toUserFacingApiError(e, { subject: "Counter catalog", action: "load catalog" })));
  }, [open, caseId, tenantId]);

  const index = useMemo(() => catalogIndex(catalog), [catalog]);

  const signalNames = useMemo(() => {
    const ctx = decisionExplain?.inference_context;
    const names = new Set<string>();
    if (ctx?.top_signals) {
      for (const s of ctx.top_signals) {
        const token = s.split(":")[0]?.trim();
        if (token) names.add(token);
      }
    }
    if (ctx?.velocity_events_24h != null) names.add("velocity_events_24h");
    return [...names].slice(0, 6);
  }, [decisionExplain?.inference_context]);

  if (!open || signalNames.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-surface-700/70 bg-surface-950/30 px-3 py-2"
      aria-label="Counter transparency"
    >
      <span className="text-[10px] uppercase tracking-wide text-gray-500 shrink-0">Counters</span>
      {signalNames.map((name) => {
        const meta = index.get(name);
        return (
          <CounterTransparencyChip
            key={name}
            counterName={name}
            title={meta?.title ?? meta?.description ?? name}
            opsLink={meta?.ops_deep_link as string | undefined}
          />
        );
      })}
      {err ? <span className="text-[10px] text-rose-400/80">{err}</span> : null}
    </div>
  );
}
