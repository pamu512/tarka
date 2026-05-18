import { useCallback, useEffect, useMemo, useState } from "react";
import {
  downloadComplianceResidencyAuditCsv,
  integrations,
  type ComplianceResidencyAuditRow,
  type ResidencyAuditListParams,
} from "../../api/client";
import { toUserFacingError } from "../../utils/userFacingErrors";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;

export function ComplianceResidencyAuditViewer() {
  const [tenantId, setTenantId] = useState("");
  const [tenantIdPrefix, setTenantIdPrefix] = useState("");
  const [vendorKeyContains, setVendorKeyContains] = useState("");
  const [outcome, setOutcome] = useState("");
  const [component, setComponent] = useState("");
  const [createdAfter, setCreatedAfter] = useState("");
  const [createdBefore, setCreatedBefore] = useState("");

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [items, setItems] = useState<ComplianceResidencyAuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const queryFilters = useMemo((): ResidencyAuditListParams => {
    const f: ResidencyAuditListParams = { page, page_size: pageSize };
    if (tenantId.trim()) f.tenant_id = tenantId.trim();
    if (tenantIdPrefix.trim()) f.tenant_id_prefix = tenantIdPrefix.trim();
    if (vendorKeyContains.trim()) f.vendor_key_contains = vendorKeyContains.trim();
    if (outcome.trim()) f.outcome = outcome.trim();
    if (component.trim()) f.component = component.trim();
    if (createdAfter.trim()) f.created_after = createdAfter.trim();
    if (createdBefore.trim()) f.created_before = createdBefore.trim();
    return f;
  }, [
    page,
    pageSize,
    tenantId,
    tenantIdPrefix,
    vendorKeyContains,
    outcome,
    component,
    createdAfter,
    createdBefore,
  ]);

  const exportFilters = useMemo((): ResidencyAuditListParams => {
    const { page: _p, page_size: _ps, ...rest } = queryFilters;
    return rest;
  }, [queryFilters]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await integrations.residencyAuditList(queryFilters);
      setItems(res.items ?? []);
      setTotal(res.total ?? 0);
      setHasMore(Boolean(res.has_more));
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Residency audit log", action: "load audit page" }));
      setItems([]);
      setTotal(0);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, [queryFilters]);

  useEffect(() => {
    void load();
  }, [load]);

  const onExportCsv = useCallback(async () => {
    setExporting(true);
    setError(null);
    try {
      await downloadComplianceResidencyAuditCsv(exportFilters);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Residency audit log", action: "export CSV from server" }));
    } finally {
      setExporting(false);
    }
  }, [exportFilters]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden"
      aria-label="Compliance residency audit log (read-only)"
    >
      <div className="p-5 border-b border-surface-700 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">Immutable audit viewer</h2>
          <p className="text-sm text-gray-500 mt-1 max-w-3xl">
            <span className="text-amber-200/90 font-medium">Read-only</span> —{" "}
            <code className="text-xs text-gray-500">ComplianceResidencyAudit</code> rows from integration-ingress (
            server-side pagination and filters). CSV export streams from{" "}
            <code className="text-xs text-gray-500">GET /v1/compliance/residency/audit/export.csv</code>, not from the DOM.
          </p>
        </div>
        <button
          type="button"
          disabled={exporting}
          onClick={() => void onExportCsv()}
          className="shrink-0 rounded-lg border border-surface-600 bg-surface-800 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-surface-700 disabled:opacity-40 disabled:pointer-events-none"
        >
          {exporting ? "Exporting…" : "Export to CSV"}
        </button>
      </div>

      <div className="p-5 border-b border-surface-800 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <label className="block text-xs text-gray-500">
            Tenant id (exact)
            <input
              value={tenantId}
              onChange={(e) => {
                setTenantId(e.target.value);
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono"
              placeholder="e.g. demo"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Tenant id prefix
            <input
              value={tenantIdPrefix}
              onChange={(e) => {
                setTenantIdPrefix(e.target.value);
                setPage(1);
              }}
              disabled={Boolean(tenantId.trim())}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono disabled:opacity-40"
              placeholder="Ignored if exact tenant set"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Vendor key contains
            <input
              value={vendorKeyContains}
              onChange={(e) => {
                setVendorKeyContains(e.target.value);
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono"
              placeholder="e.g. shodan"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Outcome
            <input
              value={outcome}
              onChange={(e) => {
                setOutcome(e.target.value);
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono"
              placeholder="compliance_block | policy_block"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Component
            <input
              value={component}
              onChange={(e) => {
                setComponent(e.target.value);
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono"
              placeholder="e.g. osint"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Created after (ISO-8601)
            <input
              value={createdAfter}
              onChange={(e) => {
                setCreatedAfter(e.target.value);
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono"
              placeholder="2026-01-01T00:00:00Z"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Created before (ISO-8601, exclusive)
            <input
              value={createdBefore}
              onChange={(e) => {
                setCreatedBefore(e.target.value);
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200 font-mono"
              placeholder="2027-01-01T00:00:00Z"
              autoComplete="off"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Page size
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="mt-1 w-full rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {error && (
        <div className="mx-5 mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="overflow-x-auto">
        <table
          className="min-w-full text-left text-sm border-collapse"
          role="grid"
          aria-readonly="true"
        >
          <thead className="bg-surface-950/90 text-xs uppercase tracking-wide text-gray-500 border-b border-surface-700">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                Created
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Tenant
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Vendor
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Component
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Outcome
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Regions
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                URL preview
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Detail
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-800 text-gray-300 [&_td]:select-text">
            {loading ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-gray-500">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-gray-500">
                  No rows match the current filters.
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={row.id} className="hover:bg-surface-800/50">
                  <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs text-gray-400">
                    {row.created_at ?? "—"}
                  </td>
                  <td className="px-3 py-2 align-top font-mono text-xs">{row.tenant_id}</td>
                  <td className="px-3 py-2 align-top font-mono text-xs">{row.vendor_key}</td>
                  <td className="px-3 py-2 align-top font-mono text-xs text-gray-500">{row.component}</td>
                  <td className="px-3 py-2 align-top font-mono text-xs text-amber-200/90">{row.outcome}</td>
                  <td className="px-3 py-2 align-top text-xs text-gray-400">
                    {row.tenant_region} → {row.vendor_region}
                  </td>
                  <td className="px-3 py-2 align-top max-w-[14rem] truncate font-mono text-[11px] text-gray-500" title={row.request_url_preview ?? ""}>
                    {row.request_url_preview ?? "—"}
                  </td>
                  <td className="px-3 py-2 align-top max-w-xl text-xs text-gray-400 whitespace-pre-wrap break-words">{row.detail ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-surface-700 text-sm text-gray-400">
        <span>
          Page <span className="tabular-nums text-gray-200">{page}</span> /{" "}
          <span className="tabular-nums text-gray-200">{totalPages}</span>
          <span className="mx-2 text-surface-600">·</span>
          <span className="tabular-nums text-gray-200">{total}</span> total rows
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="rounded border border-surface-600 px-3 py-1.5 text-gray-200 hover:bg-surface-800 disabled:opacity-40 disabled:pointer-events-none"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={!hasMore || loading}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border border-surface-600 px-3 py-1.5 text-gray-200 hover:bg-surface-800 disabled:opacity-40 disabled:pointer-events-none"
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
