import { useCallback, useMemo, useState, type ReactElement } from "react";

import { PageTitle } from "@/components/PageTitle";
import { TransactionVirtualTable } from "@/components/transactions/TransactionVirtualTable";
import { buildTransactionSeed } from "@/domain/transactionSeed";
import { parseTransactionRowPayload, type TransactionRow } from "@/domain/transactionRow";
import { useResilientWebSocket } from "@/realtime/useResilientWebSocket";

const MAX_ROWS = 10_000;

function resolveTransactionsWsUrl(): string | null {
  const raw = import.meta.env.VITE_TRANSACTIONS_WS_URL?.trim();
  return raw || null;
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
    if (!row) {
      return prev;
    }
    const idx = prev.findIndex((r) => r.id === row.id);
    if (idx >= 0) {
      const next = prev.slice();
      next[idx] = row;
      return next;
    }
    return [row, ...prev].slice(0, MAX_ROWS);
  }

  if (type === "batch" && Array.isArray(o.rows)) {
    const incoming: TransactionRow[] = [];
    for (const item of o.rows) {
      const row = parseTransactionRowPayload(item);
      if (row) {
        incoming.push(row);
      }
    }
    if (incoming.length === 0) {
      return prev;
    }
    return [...incoming, ...prev].slice(0, MAX_ROWS);
  }

  const single = parseTransactionRowPayload(parsed);
  if (single) {
    return [single, ...prev].slice(0, MAX_ROWS);
  }

  return prev;
}

export default function TransactionsLiveGrid(): ReactElement {
  const seed = useMemo(() => buildTransactionSeed(MAX_ROWS), []);
  const [rows, setRows] = useState<TransactionRow[]>(seed);

  const wsUrl = useMemo(() => resolveTransactionsWsUrl(), []);

  const onWsText = useCallback((text: string) => {
    setRows((prev) => applyFeedTextMessage(prev, text));
  }, []);

  const { status, statusDetail, reconnectNow } = useResilientWebSocket(wsUrl, onWsText);

  return (
    <div className="p-6 flex flex-col gap-4 h-full min-h-0">
      <div className="flex flex-wrap items-end justify-between gap-3 shrink-0">
        <div>
          <PageTitle module="analytics">Live transaction grid</PageTitle>
          <p className="text-sm text-gray-500 mt-1 max-w-3xl">
            Virtualized TanStack Table over <span className="tabular-nums">{MAX_ROWS.toLocaleString()}</span> rows.
            Connect a feed via <code className="text-gray-400">VITE_TRANSACTIONS_WS_URL</code> (JSON messages:{" "}
            <code className="text-gray-400">{"{ type: \"upsert\", row }"}</code>,{" "}
            <code className="text-gray-400">{"{ type: \"batch\", rows }"}</code>, or a bare row object).
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

      <div className="min-h-0 flex-1 flex flex-col">
        <TransactionVirtualTable data={rows} />
      </div>
    </div>
  );
}
