import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { decisions, type DriftQueryResponse, type TenantBenchmarkExport } from "../../../../api/client";
import { DegradedModeBanner } from "../../../DegradedModeBanner";
import { useCaseWorkbench } from "../../../../context/CaseWorkbenchContext";
import { toUserFacingApiError } from "../../../../api/client";
import { trackPanelUsage } from "../../../../workbench/workbenchTelemetry";

/** E05 — benchmark export + drift query tiles. */
export function BenchmarkDriftTiles() {
  const { caseId, tenantId, isPanelOpen, togglePanel } = useCaseWorkbench();
  const [benchmark, setBenchmark] = useState<TenantBenchmarkExport | null>(null);
  const [drift, setDrift] = useState<DriftQueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const open = isPanelOpen("benchmark_drift");

  useEffect(() => {
    if (!open) return;
    trackPanelUsage("benchmark_drift", true, { caseId, tenantId });
    let cancelled = false;
    setLoading(true);
    setError(null);
    setWarnings([]);
    void Promise.allSettled([decisions.benchmarkExport(tenantId), decisions.driftQuery(tenantId)])
      .then(([benchRes, driftRes]) => {
        if (cancelled) return;
        const w: string[] = [];
        if (benchRes.status === "fulfilled") setBenchmark(benchRes.value);
        else {
          setBenchmark(null);
          if (benchRes.reason && !String(benchRes.reason).includes("404")) {
            w.push(toUserFacingApiError(benchRes.reason, { subject: "Benchmark export", action: "load benchmark" }));
          }
        }
        if (driftRes.status === "fulfilled") setDrift(driftRes.value);
        else {
          setDrift(null);
          w.push(toUserFacingApiError(driftRes.reason, { subject: "Drift query", action: "load drift summary" }));
        }
        setWarnings(w);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, caseId, tenantId]);

  if (!open) return null;

  const driftElevated = drift?.summary?.drift_elevated === true;
  const driftScore = drift?.summary?.drift_score;

  return (
    <section aria-label="Benchmark and drift" className="rounded-xl border border-surface-700 bg-surface-900/80 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Benchmark &amp; drift</h3>
        <button type="button" onClick={() => togglePanel("benchmark_drift", false)} className="text-[11px] text-gray-500 hover:text-gray-300">
          Hide
        </button>
      </div>
      <DegradedModeBanner warnings={warnings} error={error} title="Telemetry partial" onDismiss={() => setError(null)} />
      {loading ? (
        <p className="text-sm text-gray-500">Loading tenant posture…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-surface-700/80 bg-surface-950/40 p-3">
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Vertical benchmark</div>
            {benchmark ? (
              <>
                <p className="text-sm text-gray-200 font-medium tabular-nums">
                  {String(benchmark.summary?.headline ?? benchmark.exported_at ?? "Export on file")}
                </p>
                <p className="text-[11px] text-gray-500 mt-1">
                  {(benchmark.verticals?.length ?? 0) > 0
                    ? `${benchmark.verticals!.length} vertical packs scored`
                    : "Tenant export available"}
                </p>
              </>
            ) : (
              <p className="text-sm text-gray-500">No benchmark export for tenant.</p>
            )}
            <Link to={`/simulation?tenant_id=${encodeURIComponent(tenantId)}`} className="text-[11px] text-brand-400 hover:text-brand-300 mt-2 inline-block">
              Run simulation →
            </Link>
          </div>
          <div
            className={`rounded-lg border p-3 ${
              driftElevated ? "border-amber-500/35 bg-amber-950/20" : "border-surface-700/80 bg-surface-950/40"
            }`}
          >
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Calibration drift</div>
            {drift ? (
              <>
                <p className={`text-sm font-medium ${driftElevated ? "text-amber-200" : "text-gray-200"}`}>
                  {driftElevated ? "Elevated drift" : "Within guardrails"}
                </p>
                <p className="text-[11px] text-gray-500 mt-1 tabular-nums">
                  score {driftScore != null ? Number(driftScore).toFixed(3) : "—"} · {drift.summary?.hint ?? "monitor"}
                </p>
              </>
            ) : (
              <p className="text-sm text-gray-500">Drift query unavailable.</p>
            )}
            <Link to={`/ops/calibration?tenant_id=${encodeURIComponent(tenantId)}`} className="text-[11px] text-brand-400 hover:text-brand-300 mt-2 inline-block">
              Ops calibration →
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}
