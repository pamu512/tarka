"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { DecisionDetail } from "@/components/decision-detail";
import { LiveTickerRow } from "@/components/live-ticker/LiveTickerRow";
import { getAuditRecentUrl } from "@/lib/audit-recent-url";
import type { AuditRecentItem, AuditRecentResponse } from "@/types/audit-recent";

const POLL_MS = 2000;
const VISIBLE = 10;

const fetcher = async (url: string): Promise<AuditRecentResponse> => {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Audit recent request failed (${res.status})`);
  }
  return res.json() as Promise<AuditRecentResponse>;
};

function sliceLatest(items: AuditRecentItem[] | undefined): AuditRecentItem[] {
  if (!items?.length) return [];
  return items.slice(0, VISIBLE);
}

function LoadingSkeleton() {
  return (
    <tbody aria-hidden>
      {Array.from({ length: VISIBLE }, (_, i) => (
        <tr key={i} className="h-10 border-b border-slate-800/40">
          <td colSpan={4} className="px-4 py-2">
            <div className="h-4 w-full rounded bg-slate-800/60" />
          </td>
        </tr>
      ))}
    </tbody>
  );
}

export function LiveTicker() {
  const [detailTxnId, setDetailTxnId] = useState<string | null>(null);
  const closeDetail = useCallback(() => setDetailTxnId(null), []);

  const url = useMemo(() => getAuditRecentUrl(), []);

  const { data, error, isLoading } = useSWR(url, fetcher, {
    refreshInterval: POLL_MS,
    revalidateOnFocus: true,
    dedupingInterval: 100,
  });

  const rows = useMemo(() => sliceLatest(data?.items), [data?.items]);

  return (
    <section
      aria-label="Live transaction ticker"
      className="relative flex min-h-[28rem] flex-col rounded-md border border-slate-800 bg-slate-950/80"
    >
      {detailTxnId ? (
        <DecisionDetail
          key={detailTxnId}
          transactionId={detailTxnId}
          onClose={closeDetail}
        />
      ) : null}
      <header className="flex h-11 shrink-0 items-center border-b border-slate-800 px-4">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Live audit stream
        </h2>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        {error ? (
          <p className="p-4 text-xs text-red-400">{error.message}</p>
        ) : (
          <table className="w-full table-fixed border-collapse text-left text-xs">
            <thead className="sticky top-0 z-[1] bg-slate-950 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="w-[148px] px-4 py-2">Timestamp</th>
                <th className="px-4 py-2">Transaction ID</th>
                <th className="w-[104px] px-4 py-2 text-right">Amount</th>
                <th className="w-[132px] px-4 py-2">Status</th>
              </tr>
            </thead>
            {isLoading && !data ? (
              <LoadingSkeleton />
            ) : (
              <tbody>
                {rows.map((row) => (
                  <LiveTickerRow
                    key={row.transaction_id}
                    timestamp={row.timestamp}
                    transaction_id={row.transaction_id}
                    amount_cents={row.amount_cents}
                    status={row.status}
                    onSelect={setDetailTxnId}
                  />
                ))}
              </tbody>
            )}
          </table>
        )}
      </div>
    </section>
  );
}
