import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import { fetchAnalyticsTransactionsPage } from "@/api/orchestratorAnalytics";
import { HardwareSignalDiffPanel } from "@/components/transactions/HardwareSignalDiffPanel";
import { PageTitle } from "@/components/PageTitle";
import { TransactionVirtualTable } from "@/components/transactions/TransactionVirtualTable";
import type { TransactionRow } from "@/domain/transactionRow";
import { parseTransactionRowPayload } from "@/domain/transactionRow";
import { mapAnalyticsTransactionRow } from "@/utils/mapAnalyticsTransactionRow";
import { toUserFacingError } from "@/utils/userFacingErrors";
import { useResilientWebSocket } from "@/realtime/useResilientWebSocket";

const PAGE_SIZE = 200;
const MAX_BUFFERED_ROWS = 12_000;

function resolveTransactionsWsUrl(): string | null {
  const raw = import.meta.env.VITE_TRANSACTIONS_WS_URL?.trim();
  return raw || null;
}

function mergeRowsDeduped(prev: TransactionRow[], incoming: TransactionRow[]): TransactionRow[] {
  if (incoming.length === 0) return prev;
  const seen = new Set(prev.map((r) => r.id));
  const merged = [...prev];
  for (const row of incoming) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    merged.push(row);
  }
  return merged.length > MAX_BUFFERED_ROWS ? merged.slice(0, MAX_BUFFERED_ROWS) : merged;
}

function prependLiveRow(prev: TransactionRow[], row: TransactionRow): TransactionRow[] {
  const idx = prev.findIndex((r) => r.id === row.id);
  if (idx >= 0) {
    const next = prev.slice();
    next[idx] = row;
    return next;
  }
  return [row, ...prev].slice(0, MAX_BUFFERED_ROWS);
}

function applyFeedTextMessage(prev: TransactionRow[], text: string): TransactionRow[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch {
    return prev;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return prev;
  }
  const o = parsed as Record<string, unknown>;
  const type = typeof o.type === "string" ? o.type : "";

  if (type === "upsert") {
    const row = parseTransactionRowPayload(o.row);
    if (!row) return prev;
    return prependLiveRow(prev, row);
  }

  if (type === "batch" && Array.isArray(o.rows)) {
    let next = prev;
    for (const item of o.rows) {
      const row = parseTransactionRowPayload(item);
      if (row) next = prependLiveRow(next, row);
    }
    return next;
  }

  const single = parseTransactionRowPayload(parsed);
  if (single) return prependLiveRow(prev, single);
  return prev;
}

export default function TransactionsLiveGrid(): ReactElement {
  const [rows, setRows] = useState<TransactionRow[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const nextPageTokenRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastQueryMs, setLastQueryMs] = useState<number | null>(null);
  const [backend, setBackend] = useState<string | null>(null);

  const wsUrl = useMemo(() => resolveTransactionsWsUrl(), []);

  useEffect(() => {
    let cancelled = false;
    nextPageTokenRef.current = null;
    setLoadingInitial(true);
    setError(null);
    setRows([]);
    setHasMore(true);

    (async () => {
      try {
        const res = await fetchAnalyticsTransactionsPage({ limit: PAGE_SIZE });
        if (cancelled) return;
        const mapped = res.rows
          .map((r) => mapAnalyticsTransactionRow(r))
          .filter((r): r is TransactionRow => r != null);
        setRows(mapped);
        nextPageTokenRef.current = res.next_cursor;
        setHasMore(Boolean(res.next_cursor));
        setLastQueryMs(res.query_ms);
        setBackend(res.backend);
      } catch (e) {
        if (!cancelled) {
          setError(toUserFacingError(e, { subject: "Transaction grid", action: "load DuckDB page" }));
          setRows([]);
          setHasMore(false);
        }
      } finally {
        if (!cancelled) setLoadingInitial(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const loadMore = useCallback(async () => {
    if (!hasMore || loadingMore || loadingInitial) return;
    if (rows.length >= MAX_BUFFERED_ROWS) {
      setHasMore(false);
      return;
    }
    const pageToken = nextPageTokenRef.current;
    if (!pageToken) return;

    setLoadingMore(true);
    setError(null);
    try {
      const res = await fetchAnalyticsTransactionsPage({ limit: PAGE_SIZE, cursor: pageToken });
      nextPageTokenRef.current = res.next_cursor;
      const mapped = res.rows
        .map((r) => mapAnalyticsTransactionRow(r))
        .filter((r): r is TransactionRow => r != null);
      const projected = rows.length + mapped.length;
      setRows((prev) => mergeRowsDeduped(prev, mapped));
      setHasMore(Boolean(res.next_cursor) && projected <= MAX_BUFFERED_ROWS);
      setLastQueryMs(res.query_ms);
      setBackend(res.backend);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Transaction grid", action: "load next page" }));
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  }, [hasMore, loadingInitial, loadingMore, rows.length]);

  const onWsText = useCallback((text: string) => {
    setRows((prev) => applyFeedTextMessage(prev, text));
  }, []);

  const toggleCompare = useCallback((rowId: string) => {
    setCompareIds((prev) => {
      if (prev.includes(rowId)) return prev.filter((x) => x !== rowId);
      if (prev.length < 2) return [...prev, rowId];
      return [prev[1]!, rowId];
    });
  }, []);

  const comparePair = useMemo((): readonly [TransactionRow, TransactionRow] | null => {
    if (compareIds.length !== 2) return null;
    const m = new Map(rows.map((r) => [r.id, r]));
    const a = m.get(compareIds[0]!);
    const b = m.get(compareIds[1]!);
    if (!a || !b) return null;
    return [a, b];
  }, [rows, compareIds]);

  const { status, statusDetail, reconnectNow } = useResilientWebSocket(wsUrl, onWsText);

  const atBufferCap = rows.length >= MAX_BUFFERED_ROWS;

  const duckBadge =
    lastQueryMs != null ? (
      <span className="ml-2 text-emerald-400/90">
        {backend ?? "duckdb"} · {lastQueryMs.toFixed(1)}ms
      </span>
    ) : null;

  return (
    <div className="p-6 flex flex-col gap-4 h-full min-h-0">
      <div className="flex flex-wrap items-end justify-between gap-3 shrink-0">
        <div>
          <PageTitle module="analytics">Live transaction grid</PageTitle>
          <p className="text-sm text-gray-500 mt-1 max-w-3xl">
            Infinite scroll over the DuckDB analytical layer (<code className="text-gray-400">v_analytics_transactions</code>
            ) with keyset cursors — ~5ms fetches per page. TanStack Virtual keeps the DOM small; optional WS feed prepends
            live upserts via <code className="text-gray-400">VITE_TRANSACTIONS_WS_URL</code>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`rounded-md border px-2 py-1 font-medium tabular-nums ${
              status === "open"
                ? "border-emerald-500/40 text-emerald-300 bg-emerald-500/10"
                : status === "reconnecting" || status === "connecting"
                  ? "border-amber-500/40 text-amber-200 bg-amber-500/10"
                  : status === "error"
                    ? "border-red-500/40 text-red-300 bg-red-500/10"
                    : "border-surface-600 text-gray-400 bg-surface-800"
            }`}
          >
            WS: {status}
          </span>
          {statusDetail ? (
            <span className="text-gray-500 max-w-md truncate" title={statusDetail}>
              {statusDetail}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => reconnectNow()}
            className="rounded-md border border-surface-600 bg-surface-800 px-3 py-1 text-gray-200 hover:bg-surface-700 transition-colors"
          >
            Reconnect
          </button>
        </div>
      </div>

      {error ? (
        <p className="text-sm text-red-400 shrink-0">{error}</p>
      ) : null}

      {atBufferCap ? (
        <p className="text-[11px] text-amber-400/90 shrink-0 border border-amber-500/30 rounded-lg px-3 py-2 bg-amber-500/5">
          Buffered row cap ({MAX_BUFFERED_ROWS.toLocaleString()}) reached — scroll back up or reload to explore other windows.
        </p>
      ) : null}

      <div className="min-h-0 flex-1 flex flex-col gap-4">
        {loadingInitial ? (
          <div className="flex flex-1 items-center justify-center py-24">
            <div className="w-9 h-9 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <TransactionVirtualTable
            data={rows}
            compareIds={compareIds}
            onToggleCompare={toggleCompare}
            loadingMore={loadingMore}
            onScrollNearEnd={loadMore}
            footerExtra={duckBadge}
          />
        )}
        {comparePair ? (
          <HardwareSignalDiffPanel left={comparePair[0]} right={comparePair[1]} />
        ) : (
          <p className="text-[11px] text-gray-600 border border-dashed border-surface-700 rounded-lg px-3 py-2 shrink-0">
            Visual diff: check two rows (max two selections; third replaces the oldest). When shared hardware signals reach
            80% agreement, matching keys use emerald emphasis.
          </p>
        )}
      </div>
    </div>
  );
}
