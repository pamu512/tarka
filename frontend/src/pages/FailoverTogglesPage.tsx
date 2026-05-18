import { useCallback, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useFailoverPlanes } from "../context/FailoverPlaneContext";
import { toUserFacingError } from "../utils/userFacingErrors";

function latencyTone(ms: number | null, high: number): "ok" | "warn" | "na" {
  if (ms == null || !Number.isFinite(ms)) return "na";
  if (ms < high * 0.5) return "ok";
  if (ms < high) return "warn";
  return "warn";
}

export default function FailoverTogglesPage(): ReactElement {
  const { graphPlaneDisabled, aiPlaneDisabled, graphLatencyMsP95, aiLatencyMsP95, updatedAt, error, setPlanes, refresh } =
    useFailoverPlanes();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useRegisterPageMeta({ title: "Failover toggles", subtitle: "Graph & AI planes" });

  const toggleGraph = useCallback(
    async (enabled: boolean) => {
      setBusy(true);
      setActionError(null);
      try {
        await setPlanes({ graph_plane_disabled: !enabled, ai_plane_disabled: aiPlaneDisabled });
      } catch (e) {
        setActionError(toUserFacingError(e, { subject: "Failover toggles", action: "update graph plane" }));
      } finally {
        setBusy(false);
      }
    },
    [aiPlaneDisabled, setPlanes],
  );

  const toggleAi = useCallback(
    async (enabled: boolean) => {
      setBusy(true);
      setActionError(null);
      try {
        await setPlanes({ graph_plane_disabled: graphPlaneDisabled, ai_plane_disabled: !enabled });
      } catch (e) {
        setActionError(toUserFacingError(e, { subject: "Failover toggles", action: "update AI plane" }));
      } finally {
        setBusy(false);
      }
    },
    [graphPlaneDisabled, setPlanes],
  );

  const graphLt = latencyTone(graphLatencyMsP95, 400);
  const aiLt = latencyTone(aiLatencyMsP95, 1500);

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="compliance">Failover toggles</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            When graph or AI latency spikes, analysts can <strong className="text-gray-400">manually shed load</strong> by
            disabling whole planes. Graph Explorer and Investigation Copilot read this state from{" "}
            <code className="text-gray-400">GET /api/ingress/v1/ops/failover-toggles</code> (polls every few seconds).
            Re-enable as soon as dependencies recover.
          </p>
          {updatedAt ? (
            <p className="text-[11px] text-gray-600 mt-2">
              Last control-plane update: <span className="font-mono text-gray-500">{updatedAt}</span>
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <button
            type="button"
            onClick={() => void refresh()}
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700"
          >
            Refresh
          </button>
          <Link
            to="/ops/infra"
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700"
          >
            Infra probes
          </Link>
        </div>
      </div>

      {(error || actionError) && (
        <div className="rounded-lg border border-rose-500/35 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 space-y-2">
          {error ? <p>{error}</p> : null}
          {actionError ? <p>{actionError}</p> : null}
          <SupportIdHint
            message={error ?? actionError ?? ""}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      )}

      <div className="space-y-4">
        <section className="rounded-xl border border-surface-700 bg-surface-900/70 p-5 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-gray-200">Graph plane</h2>
              <p className="text-xs text-gray-500 mt-1 max-w-xl">
                JanusGraph / graph-service traffic. Disable to stop new subgraph pulls during incidents (cases still
                load; graph panels show a banner).
              </p>
            </div>
            <div className="text-right text-[11px] text-gray-500 space-y-0.5">
              <div>
                p95 latency:{" "}
                <span
                  className={`font-mono ${
                    graphLt === "ok" ? "text-emerald-300" : graphLt === "warn" ? "text-amber-200" : "text-gray-500"
                  }`}
                >
                  {graphLatencyMsP95 != null ? `${Math.round(graphLatencyMsP95)} ms` : "—"}
                </span>
              </div>
              <div className={graphPlaneDisabled ? "text-rose-300 font-medium" : "text-emerald-300/90"}>
                {graphPlaneDisabled ? "DISABLED" : "ENABLED"}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-gray-300">Allow graph plane</span>
            <button
              type="button"
              role="switch"
              aria-checked={!graphPlaneDisabled}
              disabled={busy}
              onClick={() => void toggleGraph(graphPlaneDisabled)}
              className={`relative h-7 w-12 shrink-0 rounded-full border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 disabled:opacity-45 ${
                !graphPlaneDisabled
                  ? "bg-emerald-900/55 border-emerald-500/45"
                  : "bg-surface-800 border-surface-600"
              }`}
            >
              <span
                className={`absolute top-1 left-1 h-5 w-5 rounded-full bg-gray-300 shadow transition-transform ${
                  !graphPlaneDisabled ? "translate-x-5 bg-emerald-200" : "translate-x-0"
                }`}
              />
            </button>
          </div>
        </section>

        <section className="rounded-xl border border-surface-700 bg-surface-900/70 p-5 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-gray-200">AI plane</h2>
              <p className="text-xs text-gray-500 mt-1 max-w-xl">
                Investigation Copilot, ML scoring hooks, and related signal-plane inference. Disable to shed LLM/ONNX
                pressure while keeping deterministic rule paths online.
              </p>
            </div>
            <div className="text-right text-[11px] text-gray-500 space-y-0.5">
              <div>
                p95 latency:{" "}
                <span
                  className={`font-mono ${
                    aiLt === "ok" ? "text-emerald-300" : aiLt === "warn" ? "text-amber-200" : "text-gray-500"
                  }`}
                >
                  {aiLatencyMsP95 != null ? `${Math.round(aiLatencyMsP95)} ms` : "—"}
                </span>
              </div>
              <div className={aiPlaneDisabled ? "text-rose-300 font-medium" : "text-emerald-300/90"}>
                {aiPlaneDisabled ? "DISABLED" : "ENABLED"}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-gray-300">Allow AI plane</span>
            <button
              type="button"
              role="switch"
              aria-checked={!aiPlaneDisabled}
              disabled={busy}
              onClick={() => void toggleAi(aiPlaneDisabled)}
              className={`relative h-7 w-12 shrink-0 rounded-full border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 disabled:opacity-45 ${
                !aiPlaneDisabled ? "bg-emerald-900/55 border-emerald-500/45" : "bg-surface-800 border-surface-600"
              }`}
            >
              <span
                className={`absolute top-1 left-1 h-5 w-5 rounded-full bg-gray-300 shadow transition-transform ${
                  !aiPlaneDisabled ? "translate-x-5 bg-emerald-200" : "translate-x-0"
                }`}
              />
            </button>
          </div>
        </section>
      </div>

      <p className="text-[11px] text-gray-600 leading-relaxed">
        Production wiring: persist toggles in Redis or the control-plane service so all UI nodes and edge workers honor
        the same flags; audit every change (actor, reason) for SOC2.
      </p>
    </div>
  );
}
