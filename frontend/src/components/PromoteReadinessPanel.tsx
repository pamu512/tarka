import { useCallback, useEffect, useState } from "react";

import { rules } from "@/api/client";

type Readiness = Awaited<ReturnType<typeof rules.shadowPackReadiness>>;

/** One view per draft: gates, metrics, calibration window — honest nulls as "— unknown". */
export function PromoteReadinessPanel({
  draftId,
  tenantId,
}: {
  draftId: string;
  tenantId: string;
}) {
  const [data, setData] = useState<Readiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchIt = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await rules.shadowPackReadiness(draftId, tenantId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [draftId, tenantId]);

  useEffect(() => {
    void fetchIt();
  }, [fetchIt]);

  const metric = (v: number | null | undefined, fmt: (n: number) => string) =>
    v == null ? <span className="text-gray-600">— unknown</span> : <span className="font-mono">{fmt(v)}</span>;

  const w = data?.calibration_window;

  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Promote readiness · {draftId}
        </h3>
        <button
          onClick={() => void fetchIt()}
          disabled={loading}
          className="text-[10px] px-2 py-1 rounded bg-surface-700 hover:bg-surface-600 text-gray-300 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <div className="text-xs text-red-400">{error}</div>}

      {data && (
        <>
          <div className="flex items-center gap-2">
            <span
              className={`text-xs font-medium px-2 py-0.5 rounded ${
                data.ready ? "bg-green-500/20 text-green-400" : "bg-amber-500/20 text-amber-400"
              }`}
            >
              {data.ready ? "Ready" : "Not ready"}
            </span>
            {data.blockers.map((b) => (
              <span key={b} className="text-[10px] font-mono text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded">
                {b}
              </span>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="bg-surface-800 rounded-lg p-2">
              <div className="text-gray-500 mb-1">rule hit rate</div>
              {metric(data.desk_promote_gate?.metrics?.rule_hit_rate, (n) => `${(n * 100).toFixed(1)}%`)}
            </div>
            <div className="bg-surface-800 rounded-lg p-2">
              <div className="text-gray-500 mb-1">shadow divergence</div>
              {metric(data.desk_promote_gate?.metrics?.shadow_divergence, (n) => n.toFixed(3))}
            </div>
          </div>

          {w && (
            <div className="text-[11px] text-gray-400 bg-surface-800 rounded-lg p-2 font-mono">
              calibration window: {w.days ?? 0} / {w.min_days ?? "?"} days ·{" "}
              {w.label_count ?? 0} / {w.min_labels ?? "?"} labels
              {w.fp_rate != null ? ` · fp ${(w.fp_rate * 100).toFixed(1)}%` : ""}
            </div>
          )}

          <p className="text-[10px] text-gray-600">
            Gates are the same ones Promote enforces. Readiness never promotes; the human does.
          </p>
        </>
      )}
    </div>
  );
}
