"use client";

import useSWR from "swr";
import type { TimelineResponse } from "@/types/timeline";

export type TimelineViewProps = {
  transactionId: string;
};

function timelineUrl(transactionId: string): string {
  return `/api/v1/transactions/${encodeURIComponent(transactionId)}/timeline`;
}

const fetcher = async (url: string): Promise<TimelineResponse> => {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Timeline failed (${res.status})`);
  }
  return res.json() as Promise<TimelineResponse>;
};

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function TimelineView({ transactionId }: TimelineViewProps) {
  const url = timelineUrl(transactionId);
  const { data, error, isLoading } = useSWR(url, fetcher);

  if (isLoading && !data) {
    return (
      <section className="rounded-md border border-slate-800/90 bg-slate-900/25 p-4">
        <p className="text-xs text-slate-500">Loading entity timeline…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="rounded-md border border-red-900/50 bg-red-950/20 p-4">
        <p className="text-xs text-red-300">{error.message}</p>
      </section>
    );
  }

  if (!data) return null;

  return (
    <section className="flex flex-col gap-3 rounded-md border border-slate-800/90 bg-slate-900/25 p-4">
      <div className="flex flex-col gap-0.5">
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
          Entity timeline
        </h3>
        <p className="text-[11px] leading-snug text-slate-500">
          All audit events for this transaction and linked history across cases (device ID and IP
          matches).
        </p>
      </div>

      {data.warning ? (
        <p className="rounded border border-amber-900/40 bg-amber-950/25 px-3 py-2 text-xs text-amber-200/90">
          {data.warning}
        </p>
      ) : null}

      {data.alerts?.length ? (
        <ul className="space-y-2">
          {data.alerts.map((a) => (
            <li
              key={a}
              className="rounded border border-orange-500/60 bg-orange-950/35 px-3 py-2 text-xs font-medium text-orange-100"
            >
              {a}
            </li>
          ))}
        </ul>
      ) : null}

      {data.anchor_case_number ? (
        <p className="text-[11px] text-slate-400">
          Current investigation case:{" "}
          <span className="font-mono text-slate-200">#{data.anchor_case_number}</span>
          {data.anchor_timestamp ? (
            <>
              {" "}
              · anchor{" "}
              <span className="font-mono text-slate-300">{formatTs(data.anchor_timestamp)}</span>
            </>
          ) : null}
        </p>
      ) : null}

      {data.events.length === 0 ? (
        <p className="text-xs text-slate-500">No timeline events found for this entity yet.</p>
      ) : (
        <ol className="relative ms-2 border-s border-slate-700/80 ps-6">
          {data.events.map((ev, idx) => {
            const cross = ev.highlight === "cross_case";
            return (
              <li key={`${ev.audit_log_id}-${idx}`} className="relative pb-6 last:pb-0">
                <span
                  className={`absolute -start-[calc(0.25rem+1px)] top-1.5 size-2.5 rounded-full ring-2 ${
                    cross
                      ? "bg-orange-400 ring-orange-300/80"
                      : "bg-slate-500 ring-slate-700"
                  }`}
                  aria-hidden
                />
                <div
                  className={`rounded-md border px-3 py-2 ${
                    cross
                      ? "border-orange-500/80 bg-orange-950/30 ring-1 ring-orange-500/25"
                      : "border-slate-800 bg-slate-950/50"
                  }`}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-mono text-[11px] text-slate-300">{ev.transaction_id}</span>
                    <time className="text-[10px] text-slate-500" dateTime={ev.timestamp}>
                      {formatTs(ev.timestamp)}
                    </time>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400">
                    Case <span className="font-mono text-slate-200">#{ev.investigation_case_number}</span>
                    {" · "}
                    <span className="uppercase">{ev.case_outcome}</span>
                    {typeof ev.amount === "number" ? (
                      <>
                        {" · "}
                        <span className="font-mono">${ev.amount.toFixed(2)}</span>
                      </>
                    ) : null}
                  </p>
                  <p className="mt-1 text-[10px] text-slate-500">
                    Matched via {ev.matched_via.replace("_", " ")}
                    {ev.device_id ? (
                      <>
                        {" · "}
                        <span className="font-mono text-slate-400">device {ev.device_id}</span>
                      </>
                    ) : null}
                    {ev.ip_address ? (
                      <>
                        {" · "}
                        <span className="font-mono text-slate-400">{ev.ip_address}</span>
                      </>
                    ) : null}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
