import { useCallback, useEffect, useRef, useState } from "react";
import { integrations, type ResidencyMatrixResponse } from "../../api/client";
import { toUserFacingError } from "../../utils/userFacingErrors";

const DEBOUNCE_MS = 450;

function cellKey(tenantId: string, vendorKey: string): string {
  return `${tenantId}::${vendorKey}`;
}

function regionBadgeClass(region: string): string {
  const r = (region || "").toUpperCase();
  if (r === "EU") return "bg-sky-500/15 text-sky-300 border-sky-500/30";
  if (r === "US") return "bg-amber-500/15 text-amber-200 border-amber-500/35";
  return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
}

export function DataResidencyMatrix() {
  const [matrix, setMatrix] = useState<ResidencyMatrixResponse | null>(null);
  const [cells, setCells] = useState<Record<string, boolean>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const debouncers = useRef<Map<string, number>>(new Map());
  const pendingPayload = useRef<Map<string, { tenant_id: string; vendor_key: string; blocked: boolean }>>(new Map());

  const mergeServerCells = useCallback((m: ResidencyMatrixResponse) => {
    setMatrix(m);
    setCells({ ...(m.cells ?? {}) });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const m = await integrations.residencyMatrix();
        if (!cancelled) mergeServerCells(m);
      } catch (e) {
        if (!cancelled) setLoadError(toUserFacingError(e, { subject: "Residency matrix", action: "load matrix" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mergeServerCells]);

  useEffect(() => {
    return () => {
      for (const id of debouncers.current.values()) window.clearTimeout(id);
      debouncers.current.clear();
      pendingPayload.current.clear();
    };
  }, []);

  const schedulePut = useCallback((tenantId: string, vendorKey: string, blocked: boolean, rollbackValue: boolean) => {
    const ck = cellKey(tenantId, vendorKey);
    pendingPayload.current.set(ck, { tenant_id: tenantId, vendor_key: vendorKey, blocked });
    const prevId = debouncers.current.get(ck);
    if (prevId != null) window.clearTimeout(prevId);

    const tid = window.setTimeout(() => {
      debouncers.current.delete(ck);
      const body = pendingPayload.current.get(ck);
      pendingPayload.current.delete(ck);
      if (!body) return;

      void (async () => {
        setSaveError(null);
        try {
          const updated = await integrations.residencyMatrixPut(body);
          mergeServerCells(updated);
        } catch (e) {
          setCells((prev) => ({ ...prev, [ck]: rollbackValue }));
          setSaveError(
            toUserFacingError(e, {
              subject: "Residency matrix",
              action: `save block rule for ${tenantId} × ${vendorKey}`,
            }),
          );
        }
      })();
    }, DEBOUNCE_MS);
    debouncers.current.set(ck, tid);
  }, [mergeServerCells]);

  const onToggle = useCallback(
    (tenantId: string, vendorKey: string) => {
      const ck = cellKey(tenantId, vendorKey);
      setCells((prev) => {
        const rollbackValue = Boolean(prev[ck]);
        const nextBlocked = !rollbackValue;
        queueMicrotask(() => schedulePut(tenantId, vendorKey, nextBlocked, rollbackValue));
        return { ...prev, [ck]: nextBlocked };
      });
    },
    [schedulePut],
  );

  if (loading) {
    return (
      <section className="rounded-xl border border-surface-700 bg-surface-900/80 p-6">
        <p className="text-sm text-gray-500">Loading data residency matrix…</p>
      </section>
    );
  }

  if (loadError || !matrix) {
    return (
      <section className="rounded-xl border border-rose-500/25 bg-rose-500/5 p-4 text-sm text-rose-200">
        {loadError ?? "Matrix unavailable."}
      </section>
    );
  }

  const tenants = matrix.tenants ?? [];
  const vendors = matrix.vendors ?? [];

  return (
    <section className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden">
      <div className="p-5 border-b border-surface-700 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">Data residency matrix</h2>
          <p className="text-sm text-gray-500 mt-1 max-w-3xl">
            Rows are tenants; columns are third-party vendors (OSINT + integration connectors). Toggle{" "}
            <strong className="text-gray-400 font-medium">Block</strong> to enforce a pre-socket administrative deny —
            each change updates <span className="font-mono text-xs text-gray-500">PUT /v1/compliance/residency/matrix</span>{" "}
            (debounced {DEBOUNCE_MS} ms per cell). PUT requires an admin API key; optimistic UI rolls back on failure.
          </p>
          {matrix.legend && (
            <p className="text-xs text-gray-600 mt-2">
              <span className="text-gray-500">On:</span> {matrix.legend.toggle_on} ·{" "}
              <span className="text-gray-500">Off:</span> {matrix.legend.toggle_off}
            </p>
          )}
        </div>
      </div>

      {saveError && (
        <div className="mx-5 mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {saveError}
        </div>
      )}

      <div className="overflow-x-auto max-h-[min(70vh,720px)] overflow-y-auto">
        <table className="min-w-max w-full border-collapse text-sm">
          <thead>
            <tr className="bg-surface-950/90 sticky top-0 z-20 shadow-sm">
              <th
                scope="col"
                className="sticky left-0 z-30 bg-surface-950 border-b border-r border-surface-700 px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 min-w-[11rem]"
              >
                Tenant
              </th>
              {vendors.map((v) => (
                <th
                  key={v.key}
                  scope="col"
                  className="border-b border-surface-700 px-2 py-2 text-center align-bottom min-w-[6.5rem] max-w-[8rem]"
                >
                  <div className="flex flex-col items-center gap-1">
                    <span className="font-mono text-[11px] text-gray-200 leading-tight break-all" title={v.key}>
                      {v.key}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded border tabular-nums ${regionBadgeClass(v.processing_region)}`}
                    >
                      {v.processing_region}
                    </span>
                    <span className="text-[9px] text-gray-600 uppercase">{v.source ?? ""}</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.id} className="border-b border-surface-800 hover:bg-surface-800/40">
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-surface-900 border-r border-surface-700 px-3 py-2 text-left align-middle"
                >
                  <div className="font-medium text-gray-200">{t.label ?? t.id}</div>
                  <div className="text-[11px] font-mono text-gray-500">{t.id}</div>
                  <div className={`mt-1 inline-block text-[10px] px-1.5 py-0.5 rounded border ${regionBadgeClass(t.residency_region)}`}>
                    {t.residency_region}
                  </div>
                </th>
                {vendors.map((v) => {
                  const ck = cellKey(t.id, v.key);
                  const blocked = Boolean(cells[ck]);
                  return (
                    <td key={ck} className="border-l border-surface-800/80 px-1 py-1 text-center align-middle">
                      <label className="inline-flex flex-col items-center gap-1 cursor-pointer select-none py-1">
                        <span className="text-[9px] uppercase tracking-wide text-gray-600">Block</span>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={blocked}
                          aria-label={`Block vendor ${v.key} for tenant ${t.id}`}
                          onClick={() => onToggle(t.id, v.key)}
                          className={`relative h-7 w-12 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-900 ${
                            blocked ? "bg-rose-600" : "bg-surface-600"
                          }`}
                        >
                          <span
                            className={`absolute top-0.5 left-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform ${
                              blocked ? "translate-x-5" : "translate-x-0"
                            }`}
                          />
                        </button>
                      </label>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
