import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { AuditEntry } from "../api/client";
import { decisions } from "../api/client";
import { DagTraceVisualizer } from "../components/DagTraceVisualizer";
import { PageTitle } from "../components/PageTitle";

function defaultTenantId(): string {
  try {
    const t = localStorage.getItem("tarka.tenant_id");
    if (t && t.trim()) return t.trim();
  } catch {
    /* ignore */
  }
  return "demo";
}

export default function DagTracePage() {
  const [params, setParams] = useSearchParams();
  const traceId = (params.get("trace_id") || "").trim();
  const tenantId = (params.get("tenant_id") || "").trim() || defaultTenantId();

  const [audit, setAudit] = useState<AuditEntry | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [loading, setLoading] = useState(false);

  const canLoad = traceId.length > 0;

  const load = useCallback(async () => {
    if (!canLoad) return;
    setLoading(true);
    setLoadErr("");
    setAudit(null);
    try {
      const row = await decisions.getAudit(traceId, tenantId, { detail_level: "analyst" });
      setAudit(row);
    } catch (e) {
      setAudit(null);
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [canLoad, tenantId, traceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onSubmitIds = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const tid = String(fd.get("trace_id") || "").trim();
      const ten = String(fd.get("tenant_id") || "").trim();
      const next = new URLSearchParams();
      if (tid) next.set("trace_id", tid);
      if (ten) next.set("tenant_id", ten);
      setParams(next, { replace: true });
    },
    [setParams],
  );

  const subtitle = useMemo(
    () =>
      "Loads `GET /v1/audit/{trace_id}?tenant_id=…&detail_level=analyst` and renders `step_trace` as an evaluation DAG. " +
      "Malformed arrays are coerced with inline warnings; 403 means analyst role is required on the API.",
    [],
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <PageTitle module="investigation">
        DAG execution trace
        <span className="block text-xs font-normal text-gray-500 mt-1">{subtitle}</span>
      </PageTitle>

      <form onSubmit={onSubmitIds} className="flex flex-col sm:flex-row flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1 text-xs text-gray-500 flex-1 min-w-[200px]">
          Trace ID
          <input
            name="trace_id"
            defaultValue={traceId}
            placeholder="UUID from evaluate / case"
            className="rounded-lg border border-surface-600 bg-surface-900 px-3 py-2 text-sm text-gray-200 font-mono"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500 flex-1 min-w-[160px]">
          Tenant ID
          <input
            name="tenant_id"
            defaultValue={tenantId}
            className="rounded-lg border border-surface-600 bg-surface-900 px-3 py-2 text-sm text-gray-200"
          />
        </label>
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium shrink-0"
        >
          Load trace
        </button>
      </form>

      {loading ? <p className="text-sm text-gray-500">Loading audit…</p> : null}
      {loadErr ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-100 whitespace-pre-wrap">
          {loadErr}
        </div>
      ) : null}
      {!loading && !loadErr && audit ? <DagTraceVisualizer audit={audit} /> : null}
      {!loading && !loadErr && !audit && canLoad ? (
        <p className="text-sm text-gray-500">No data returned for this trace.</p>
      ) : null}
      {!canLoad ? <p className="text-sm text-gray-500">Enter a trace ID to load a blocked or reviewed transaction audit.</p> : null}
    </div>
  );
}
