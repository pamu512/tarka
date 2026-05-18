import { useMemo, useState } from "react";

import type { AuditEntry } from "../api/client";
import { findFailureHighlightIndex, parseStepTrace, type ParsedStepTrace, type StepTraceRow } from "../domain/dagTrace";

function statusStyles(status: string): string {
  const s = status.toLowerCase();
  if (s === "ok") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
  if (s === "failed") return "bg-rose-500/20 text-rose-200 border-rose-500/45";
  if (s === "skipped" || s === "pending") return "bg-amber-500/15 text-amber-200 border-amber-500/35";
  return "bg-surface-800 text-gray-300 border-surface-600";
}

function StepCard({
  row,
  active,
  highlight,
}: {
  row: StepTraceRow;
  active: boolean;
  highlight: boolean;
}) {
  return (
    <div
      className={`relative rounded-lg border px-3 py-2.5 text-sm transition-colors ${
        highlight
          ? "border-rose-400/90 bg-rose-950/50 ring-2 ring-rose-500/50 shadow-[0_0_0_1px_rgba(244,63,94,0.35)]"
          : active
            ? "border-brand-500/50 bg-brand-950/30"
            : "border-surface-700 bg-surface-900/80"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-gray-500 tabular-nums">#{row.index + 1}</span>
        <span className="font-semibold text-gray-100">{row.step}</span>
        <span className={`text-[11px] uppercase tracking-wide px-2 py-0.5 rounded border ${statusStyles(row.status)}`}>
          {row.status}
        </span>
        {row.duration_ms != null ? (
          <span className="text-[11px] text-gray-500 tabular-nums">{row.duration_ms.toFixed(1)} ms</span>
        ) : null}
        {row.attempts != null ? (
          <span className="text-[11px] text-gray-500">attempts {row.attempts}</span>
        ) : null}
      </div>
      {row.reason ? <p className="mt-1.5 text-xs text-gray-400 break-words">{row.reason}</p> : null}
      {highlight ? (
        <p className="mt-2 text-[11px] font-medium text-rose-300/95">Likely trigger for this outcome (heuristic)</p>
      ) : null}
    </div>
  );
}

export type DagTraceVisualizerProps = {
  audit: AuditEntry;
  /** When true, start on raw JSON instead of the timeline */
  defaultShowRaw?: boolean;
};

/**
 * Renders evaluate DAG ``step_trace`` from an audit row (analyst detail).
 * Tolerates missing / malformed traces and surfaces parse warnings.
 */
export function DagTraceVisualizer({ audit, defaultShowRaw = false }: DagTraceVisualizerProps) {
  const [showRaw, setShowRaw] = useState(defaultShowRaw);
  const [activeIndex, setActiveIndex] = useState(0);

  const parsed: ParsedStepTrace = useMemo(() => parseStepTrace(audit.step_trace), [audit.step_trace]);
  const highlightIdx = useMemo(
    () => findFailureHighlightIndex(parsed.rows, audit.decision ?? ""),
    [parsed.rows, audit.decision],
  );

  const rawBlob = useMemo(() => {
    try {
      return JSON.stringify(
        {
          trace_id: audit.trace_id,
          tenant_id: audit.tenant_id,
          entity_id: audit.entity_id,
          decision: audit.decision,
          score: audit.score,
          fallback_reason: audit.fallback_reason ?? null,
          step_trace: audit.step_trace ?? null,
        },
        null,
        2,
      );
    } catch {
      return '{"error":"could_not_stringify_trace"}';
    }
  }, [audit]);

  if (showRaw) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="text-sm px-3 py-1.5 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700"
            onClick={() => setShowRaw(false)}
          >
            DAG timeline
          </button>
          <span className="text-xs text-gray-500">Raw execution trace JSON (subset of audit fields)</span>
        </div>
        <pre className="text-xs bg-black/50 border border-surface-700 rounded-lg p-3 overflow-auto max-h-[min(70vh,720px)] text-gray-200">
          {rawBlob}
        </pre>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
          <span>
            Decision <span className="text-gray-300 font-medium">{audit.decision}</span> · score{" "}
            <span className="text-gray-300 font-mono">{audit.score}</span>
          </span>
          {audit.fallback_reason ? (
            <span className="rounded border border-amber-500/30 bg-amber-950/40 px-2 py-0.5 text-amber-200/90">
              fallback: {audit.fallback_reason}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          className="text-sm px-3 py-1.5 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700"
          onClick={() => setShowRaw(true)}
        >
          Raw JSON trace
        </button>
      </div>

      {parsed.warnings.length > 0 ? (
        <div className="rounded-lg border border-amber-500/35 bg-amber-950/25 px-3 py-2 text-xs text-amber-100/90">
          <div className="font-semibold text-amber-200/95 mb-1">Trace payload issues</div>
          <ul className="list-disc pl-4 space-y-0.5">
            {parsed.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {parsed.rows.length === 0 ? (
        <p className="text-sm text-gray-500">No execution steps to display for this audit.</p>
      ) : (
        <div className="flex gap-4">
          <div className="flex-1 space-y-0">
            {parsed.rows.map((row, i) => (
              <div key={`${row.step}-${row.index}`} className="flex gap-3 pb-5 last:pb-0">
                <div className="flex flex-col items-center shrink-0 w-6 pt-2">
                  <button
                    type="button"
                    className="h-3.5 w-3.5 rounded-full border-2 border-surface-500 bg-surface-950 shrink-0"
                    style={{
                      boxShadow: i === activeIndex ? "0 0 0 3px rgba(59,130,246,0.35)" : undefined,
                    }}
                    aria-current={i === activeIndex}
                    aria-label={`Select step ${row.step}`}
                    onClick={() => setActiveIndex(i)}
                  />
                  {i < parsed.rows.length - 1 ? <div className="w-px flex-1 min-h-[12px] bg-surface-700 mt-1" aria-hidden /> : null}
                </div>
                <div className="flex-1 min-w-0">
                  <StepCard row={row} active={i === activeIndex} highlight={highlightIdx === i} />
                </div>
              </div>
            ))}
          </div>
          <aside className="hidden lg:block w-64 shrink-0 text-xs text-gray-500 border border-surface-800 rounded-lg p-3 bg-surface-900/40">
            <div className="font-semibold text-gray-400 mb-2">Step detail</div>
            <pre className="text-[11px] text-gray-400 overflow-auto max-h-64 whitespace-pre-wrap break-words">
              {JSON.stringify(parsed.rows[Math.min(activeIndex, parsed.rows.length - 1)]?.raw ?? {}, null, 2)}
            </pre>
          </aside>
        </div>
      )}
    </div>
  );
}
