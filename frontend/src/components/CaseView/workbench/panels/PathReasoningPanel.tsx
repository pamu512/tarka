import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { cases, type GraphPathExplanation } from "../../../../api/client";
import { DegradedModeBanner } from "../../../DegradedModeBanner";
import { useCaseWorkbench } from "../../../../context/CaseWorkbenchContext";
import { toUserFacingApiError } from "../../../../api/client";
import { trackPanelUsage } from "../../../../workbench/workbenchTelemetry";

/** E03 — path reasoning from case-api path-explain proxy. */
export function PathReasoningPanel() {
  const { caseId, tenantId, caseData, isPanelOpen, togglePanel } = useCaseWorkbench();
  const [data, setData] = useState<GraphPathExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = isPanelOpen("path_reasoning");

  useEffect(() => {
    if (!open || !caseData) return;
    trackPanelUsage("path_reasoning", true, { caseId, tenantId });
    let cancelled = false;
    setLoading(true);
    setError(null);
    void cases
      .pathExplain(caseId, tenantId, { depth: 3, limit: 8 })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) {
          setData(null);
          setError(toUserFacingApiError(e, { subject: "Path reasoning", action: "load path explanation" }));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, caseId, tenantId, caseData]);

  if (!open) return null;

  return (
    <section
      aria-label="Path reasoning"
      className="rounded-xl border border-surface-700 bg-surface-900/80 p-4 space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Path reasoning</h3>
        <button
          type="button"
          onClick={() => togglePanel("path_reasoning", false)}
          className="text-[11px] text-gray-500 hover:text-gray-300"
        >
          Hide
        </button>
      </div>
      <DegradedModeBanner error={error} title="Path explain unavailable" onDismiss={() => setError(null)} />
      {loading ? (
        <p className="text-sm text-gray-500">Loading graph paths for {caseData?.entity_id ?? "entity"}…</p>
      ) : data ? (
        <>
          <p className="text-sm text-gray-300 leading-relaxed">{data.risk_narrative}</p>
          <ul className="space-y-3">
            {data.paths.slice(0, 5).map((p) => (
              <li key={`${p.entity_id}-${p.distance}`} className="rounded-lg border border-surface-700/80 p-3">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
                  <span className="font-mono text-brand-300 truncate max-w-full">{p.entity_id}</span>
                  <span className="text-gray-500">hop {p.distance}</span>
                  <span className="text-gray-400 tabular-nums">risk {(p.propagated_risk_score * 100).toFixed(0)}%</span>
                </div>
                <p className="mt-1 text-sm text-gray-300">{p.path_description}</p>
                {p.hops.length > 0 ? (
                  <p className="mt-1 text-[11px] text-gray-500 font-mono truncate">
                    {p.hops.map((h) => h.entity_id).join(" → ")}
                  </p>
                ) : null}
                {p.reasons.length > 0 ? (
                  <ul className="mt-2 list-disc pl-4 text-[11px] text-gray-400">
                    {p.reasons.slice(0, 3).map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : !error ? (
        <p className="text-sm text-gray-500">No path explanations returned.</p>
      ) : null}
      <p className="text-[11px] text-gray-600">
        <Link to={`/graph?entity_id=${encodeURIComponent(caseData?.entity_id ?? "")}&tenant_id=${encodeURIComponent(tenantId)}`} className="text-brand-400 hover:text-brand-300">
          Open Graph Explorer
        </Link>
      </p>
    </section>
  );
}
