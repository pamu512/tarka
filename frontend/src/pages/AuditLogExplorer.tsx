import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import { AuditLogVirtualTable } from "@/components/audit/AuditLogVirtualTable";
import { PageTitle } from "@/components/PageTitle";
import { SupportIdHint } from "@/components/SupportIdHint";
import { decisions, type AuditRecentItem } from "@/api/client";
import { useTenantEnvironment } from "@/context/TenantEnvironmentContext";
import { toUserFacingError } from "@/utils/userFacingErrors";

const PAGE_SIZE = 250;
/** Client-side safety valve — real deployments rely on server cursors, not huge arrays. */
const MAX_BUFFERED_ROWS = 12_000;

function useDebouncedValue(v: string, ms: number): string {
  const [out, setOut] = useState(v);
  useEffect(() => {
    const t = window.setTimeout(() => setOut(v), ms);
    return () => window.clearTimeout(t);
  }, [v, ms]);
  return out;
}

export default function AuditLogExplorer(): ReactElement {
  const { tenantId, setTenantId } = useTenantEnvironment();
  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebouncedValue(searchInput.trim(), 320);

  const [items, setItems] = useState<AuditRecentItem[]>([]);
  const nextCursorRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const searchActive = debouncedSearch.length > 0;

  useEffect(() => {
    let cancelled = false;
    nextCursorRef.current = null;
    setLoadingInitial(true);
    setError(null);
    setItems([]);
    setHasMore(true);

    (async () => {
      try {
        const res = await decisions.auditExplorer({
          tenant_id: tenantId,
          limit: PAGE_SIZE,
          q: debouncedSearch || undefined,
        });
        if (cancelled) return;
        setItems(res.items);
        nextCursorRef.current = res.next_cursor;
        setHasMore(Boolean(res.next_cursor));
      } catch (e) {
        if (!cancelled) {
          setError(toUserFacingError(e, { subject: "Audit explorer", action: "load audit slice" }));
          setItems([]);
          setHasMore(false);
        }
      } finally {
        if (!cancelled) setLoadingInitial(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tenantId, debouncedSearch]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loadingMore || loadingInitial) return;
    if (items.length >= MAX_BUFFERED_ROWS) {
      setHasMore(false);
      return;
    }
    const cursor = nextCursorRef.current;
    if (!cursor) return;

    setLoadingMore(true);
    setError(null);
    try {
      const res = await decisions.auditExplorer({
        tenant_id: tenantId,
        limit: PAGE_SIZE,
        cursor,
        q: debouncedSearch || undefined,
      });
      nextCursorRef.current = res.next_cursor;
      const projected = items.length + res.items.length;
      setItems((prev) => {
        const merged = [...prev, ...res.items];
        return merged.length > MAX_BUFFERED_ROWS ? merged.slice(-MAX_BUFFERED_ROWS) : merged;
      });
      setHasMore(Boolean(res.next_cursor) && projected <= MAX_BUFFERED_ROWS);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Audit explorer", action: "load next page" }));
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  }, [debouncedSearch, hasMore, items.length, loadingInitial, loadingMore, tenantId]);

  const atBufferCap = items.length >= MAX_BUFFERED_ROWS;

  const statsLine = useMemo(() => {
    if (loadingInitial) return "Loading…";
    return `${items.length.toLocaleString()} rows buffered${atBufferCap ? " (cap reached)" : ""}`;
  }, [atBufferCap, items.length, loadingInitial]);

  return (
    <div className="flex h-full min-h-0 flex-col animate-fade-in">
      <div className="shrink-0 border-b border-surface-700 px-6 py-4 space-y-3">
        <PageTitle module="analytics">Audit Log Explorer</PageTitle>
        <p className="text-sm text-gray-500 max-w-4xl leading-relaxed">
          Cursor-paged decision audit feed with <span className="text-gray-400">windowed virtual scrolling</span> (TanStack
          Virtual + Table). Only visible rows touch the DOM — suitable when the warehouse holds millions of evaluations.
          Wire <code className="text-gray-400">GET /v1/audit/explorer</code> to ClickHouse / Postgres replicas with keyset
          pagination (avoid large OFFSET).
        </p>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-xs text-gray-500">
            Tenant
            <input
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono min-w-[14rem]"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-500 flex-1 min-w-[12rem] max-w-xl">
            Search trace / short id (substring)
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="e.g. a000001 or short prefix…"
              className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono"
            />
          </label>
          <span className="text-[11px] text-gray-600 pb-2 tabular-nums">{statsLine}</span>
        </div>
      </div>

      <div className="flex-1 min-h-0 px-6 py-4 flex flex-col gap-3">
        {error ? (
          <div className="rounded-lg border border-rose-500/35 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 shrink-0 space-y-2">
            <p>{error}</p>
            <SupportIdHint
              message={error}
              className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
              buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
            />
          </div>
        ) : null}

        {atBufferCap ? (
          <p className="text-[11px] text-amber-400/90 shrink-0 border border-amber-500/30 rounded-lg px-3 py-2 bg-amber-500/5">
            Buffered row cap ({MAX_BUFFERED_ROWS.toLocaleString()}) reached — narrow search or reload to explore other
            windows.
          </p>
        ) : null}

        {loadingInitial ? (
          <div className="flex flex-1 items-center justify-center py-24">
            <div className="w-9 h-9 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <AuditLogVirtualTable data={items} loadingMore={loadingMore} onScrollNearEnd={loadMore} />
        )}

        {searchActive && !loadingInitial ? (
          <p className="text-[11px] text-gray-600 shrink-0">
            Search scans forward in mock mode with a bounded step budget — production should push filtering into the
            warehouse.
          </p>
        ) : null}
      </div>
    </div>
  );
}
