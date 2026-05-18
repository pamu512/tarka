import { memo, type ReactElement } from "react";

import type { MarketplaceWebhookLogItem } from "@/api/client";

const GRID_COLS =
  "grid grid-cols-[minmax(148px,1fr)_minmax(72px,0.45fr)_minmax(100px,0.7fr)_minmax(100px,0.7fr)_minmax(88px,0.55fr)_minmax(72px,0.45fr)_minmax(140px,1fr)] gap-x-3 items-center px-3";

function statusChip(status: string): ReactElement {
  const s = status.toLowerCase();
  const cls =
    s === "delivered"
      ? "border-emerald-500/40 bg-emerald-950/40 text-emerald-200"
      : s === "pending"
        ? "border-amber-500/40 bg-amber-950/35 text-amber-200"
        : "border-rose-500/40 bg-rose-950/35 text-rose-200";
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}>
      {status}
    </span>
  );
}

function hostFromUrl(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url.slice(0, 32);
  }
}

const LogRow = memo(function LogRow({
  row,
  selected,
  onSelect,
}: {
  row: MarketplaceWebhookLogItem;
  selected: boolean;
  onSelect: (id: string) => void;
}): ReactElement {
  return (
    <button
      type="button"
      role="row"
      onClick={() => onSelect(row.id)}
      className={`${GRID_COLS} w-full text-left border-b border-surface-800/90 text-[12px] hover:bg-surface-900/80 py-2 ${
        selected ? "bg-brand-950/30 ring-1 ring-inset ring-brand-500/25" : "bg-surface-950/95"
      }`}
    >
      <span className="font-mono text-[11px] text-gray-500">
        {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
      </span>
      <span className="font-mono uppercase text-rose-300">{row.signal}</span>
      <span className="font-mono text-gray-400 truncate">{row.user_id ?? row.entity_id ?? "—"}</span>
      <span className="font-mono text-gray-500 truncate">{row.trace_id ?? "—"}</span>
      <span>{statusChip(row.status)}</span>
      <span className="font-mono tabular-nums text-gray-400">
        {row.http_status != null ? row.http_status : "—"}
      </span>
      <span className="font-mono text-[11px] text-gray-500 truncate" title={row.callback_url}>
        {hostFromUrl(row.callback_url)}
      </span>
    </button>
  );
});

export function WebhookLogsVirtualTable({
  data,
  selectedId,
  onSelect,
}: {
  data: readonly MarketplaceWebhookLogItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}): ReactElement {
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900/40 overflow-hidden flex flex-col min-h-0 flex-1">
      <div
        className={`${GRID_COLS} sticky top-0 z-10 border-b border-surface-700 bg-surface-900 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500`}
      >
        <span>Sent</span>
        <span>Signal</span>
        <span>User / entity</span>
        <span>Trace</span>
        <span>Status</span>
        <span>HTTP</span>
        <span>Callback</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {data.map((row) => (
          <LogRow key={row.id} row={row} selected={selectedId === row.id} onSelect={onSelect} />
        ))}
      </div>
      <div className="border-t border-surface-700 px-3 py-2 text-[11px] text-gray-500">
        {data.length.toLocaleString()} outgoing block webhooks
      </div>
    </div>
  );
}
