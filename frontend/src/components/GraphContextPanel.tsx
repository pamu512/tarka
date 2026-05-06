import { useEffect, useId, useState } from "react";

import { graph, type GraphEntityDeepContext, type GraphNode } from "../api/client";
import { toUserFacingError } from "../utils/userFacingErrors";

type LoadState = "idle" | "loading" | "ready" | "not_found" | "error";

function GraphContextPanelSkeleton() {
  return (
    <div className="space-y-4 animate-pulse" aria-busy="true" aria-label="Loading entity context">
      <div className="h-4 bg-surface-700 rounded w-2/3" />
      <div className="h-3 bg-surface-800 rounded w-full" />
      <div className="h-3 bg-surface-800 rounded w-5/6" />
      <div className="space-y-2 pt-2">
        <div className="h-3 bg-surface-800 rounded w-1/3" />
        <div className="h-20 bg-surface-800/80 rounded-lg border border-surface-700/50" />
        <div className="h-20 bg-surface-800/80 rounded-lg border border-surface-700/50" />
      </div>
      <div className="space-y-2 pt-2">
        <div className="h-3 bg-surface-800 rounded w-1/4" />
        <div className="h-16 bg-surface-800/80 rounded-lg border border-surface-700/50" />
      </div>
      <div className="space-y-2 pt-2">
        <div className="h-3 bg-surface-800 rounded w-1/3" />
        <div className="h-14 bg-surface-800/80 rounded-lg border border-surface-700/50" />
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export type GraphContextPanelProps = {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  entityId: string | null;
  /** Optional subgraph node for header chips while loading. */
  nodeHint?: GraphNode | null;
};

/**
 * Slide-over panel: loads ``graph.entityDeepContext`` when opened for a node.
 * Shows skeleton while loading; 404 is surfaced as a calm empty state (no stack traces).
 */
export function GraphContextPanel({ open, onClose, tenantId, entityId, nodeHint }: GraphContextPanelProps) {
  const titleId = useId();
  const [state, setState] = useState<LoadState>("idle");
  const [data, setData] = useState<GraphEntityDeepContext | null>(null);
  const [errMsg, setErrMsg] = useState("");

  useEffect(() => {
    if (!open) {
      setState("idle");
      setData(null);
      setErrMsg("");
    }
  }, [open]);

  useEffect(() => {
    if (!open || !entityId || !tenantId) return;
    let cancelled = false;
    setState("loading");
    setData(null);
    setErrMsg("");
    void (async () => {
      try {
        const ctx = await graph.entityDeepContext(entityId, tenantId);
        if (cancelled) return;
        if (ctx === null) {
          setState("not_found");
          return;
        }
        setData(ctx);
        setState("ready");
      } catch (e) {
        if (cancelled) return;
        setErrMsg(toUserFacingError(e, { subject: "Entity context", action: "load deep graph context" }));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, entityId, tenantId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !entityId) return null;

  return (
    <div className="fixed inset-0 z-[80] flex justify-end" role="presentation">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px]"
        aria-label="Close context panel"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative h-full w-full max-w-md border-l border-surface-700 bg-surface-950 shadow-2xl flex flex-col transition-transform duration-200"
      >
        <header className="shrink-0 border-b border-surface-800 px-4 py-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-sm font-semibold text-gray-100 truncate">
              Entity context
            </h2>
            <p className="text-xs text-gray-500 font-mono truncate mt-0.5" title={entityId}>
              {entityId}
            </p>
            {nodeHint?.labels?.length ? (
              <p className="text-[11px] text-gray-500 mt-1">
                Graph labels:{" "}
                <span className="text-gray-400">{nodeHint.labels.join(", ")}</span>
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-gray-500 hover:text-gray-200 text-sm px-2 py-1 rounded border border-transparent hover:border-surface-600"
          >
            Close
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
          {state === "loading" ? <GraphContextPanelSkeleton /> : null}

          {state === "not_found" ? (
            <div className="rounded-lg border border-surface-700 bg-surface-900/60 px-4 py-5 text-sm text-gray-400 space-y-2">
              <p className="text-gray-300 font-medium">No graph record for this entity</p>
              <p>
                The graph database does not have a vertex for this ID in tenant{" "}
                <span className="font-mono text-gray-400">{tenantId}</span>. It may be outside the indexed subgraph,
                removed, or not yet ingested.
              </p>
            </div>
          ) : null}

          {state === "error" ? (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
              {errMsg}
            </div>
          ) : null}

          {state === "ready" && data ? (
            <div className="space-y-6 text-sm">
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  Historical transactions ({data.historical_transactions.length})
                </h3>
                {data.historical_transactions.length === 0 ? (
                  <p className="text-gray-500 text-xs">No linked Payment vertices in the 2-hop neighborhood.</p>
                ) : (
                  <ul className="space-y-2 max-h-56 overflow-y-auto">
                    {data.historical_transactions.map((t) => (
                      <li
                        key={t.external_id}
                        className="rounded-lg border border-surface-800 bg-surface-900/80 px-3 py-2 text-xs space-y-1"
                      >
                        <div className="font-mono text-gray-300">{t.external_id}</div>
                        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-gray-500">
                          <span>trace</span>
                          <span className="text-gray-400 text-right">{formatCell(t.trace_id)}</span>
                          <span>amount</span>
                          <span className="text-gray-400 text-right">{formatCell(t.amount)}</span>
                          <span>decision</span>
                          <span className="text-gray-400 text-right">{formatCell(t.decision)}</span>
                          <span>ip</span>
                          <span className="text-gray-400 text-right">{formatCell(t.ip)}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  IP addresses ({data.ip_addresses.length})
                </h3>
                {data.ip_addresses.length === 0 ? (
                  <p className="text-gray-500 text-xs">No IP-like neighbors or IP properties found.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {data.ip_addresses.map((row) => (
                      <li
                        key={`${row.ip}-${row.source}`}
                        className="flex justify-between gap-2 rounded border border-surface-800 px-2 py-1.5 text-xs"
                      >
                        <span className="font-mono text-brand-200">{row.ip}</span>
                        <span className="text-gray-500 shrink-0">{row.source}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Risk history</h3>
                <ul className="space-y-2">
                  {data.risk_history.map((r, i) => (
                    <li key={`${r.recorded_at}-${i}`} className="rounded-lg border border-surface-800 bg-surface-900/80 px-3 py-2 text-xs space-y-1">
                      <div className="flex justify-between gap-2 text-gray-500">
                        <span>{r.source}</span>
                        <span className="font-mono text-gray-400">{r.recorded_at}</span>
                      </div>
                      <div className="text-gray-300">
                        score: <span className="font-mono text-amber-200/90">{formatCell(r.risk_score)}</span>
                      </div>
                      {Array.isArray(r.risk_factors) && r.risk_factors.length > 0 ? (
                        <ul className="list-disc list-inside text-gray-500">
                          {(r.risk_factors as string[]).map((f) => (
                            <li key={f}>{f}</li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
