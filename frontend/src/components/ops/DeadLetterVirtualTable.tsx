import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useMemo, useRef, type ReactElement } from "react";

import type { NatsDeadLetterItem } from "@/api/client";

const ROW_HEIGHT_PX = 40;

const GRID_COLS =
  "grid grid-cols-[72px_minmax(100px,0.7fr)_minmax(72px,0.45fr)_minmax(88px,0.55fr)_minmax(120px,0.85fr)_minmax(100px,0.75fr)_minmax(180px,1.2fr)] gap-x-3 items-center px-3";

function statusPill(code: number | null): ReactElement {
  if (code == null) {
    return <span className="text-gray-500">—</span>;
  }
  const cls =
    code >= 500
      ? "bg-rose-500/15 text-rose-200 border-rose-500/35"
      : code >= 400
        ? "bg-amber-500/15 text-amber-200 border-amber-500/35"
        : "bg-surface-800 text-gray-400 border-surface-600";
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-mono tabular-nums ${cls}`}>
      {code}
    </span>
  );
}

const VirtualRow = memo(function VirtualRow({
  row,
  virtualStart,
  virtualSize,
  selected,
  onSelect,
}: {
  row: Row<NatsDeadLetterItem>;
  virtualStart: number;
  virtualSize: number;
  selected: boolean;
  onSelect: (id: string) => void;
}): ReactElement {
  const o = row.original;
  return (
    <button
      type="button"
      role="row"
      onClick={() => onSelect(o.id)}
      className={`${GRID_COLS} w-full text-left border-b border-surface-800/90 text-gray-200 text-[12px] hover:bg-surface-900/80 ${
        selected ? "bg-brand-950/30 ring-1 ring-inset ring-brand-500/25" : "bg-surface-950/95"
      }`}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        height: virtualSize,
        transform: `translateY(${virtualStart}px)`,
      }}
    >
      <span className="font-mono tabular-nums text-gray-400 py-2">{o.sequence}</span>
      <span className="font-mono text-gray-300 truncate py-2">{o.kind}</span>
      <span className="py-2">{statusPill(o.status_code)}</span>
      <span className="font-mono text-gray-400 truncate py-2">{o.tenant_id ?? "—"}</span>
      <span className="font-mono text-gray-400 truncate py-2">{o.entity_id ?? "—"}</span>
      <span className="text-gray-400 truncate py-2">{o.event_type ?? "—"}</span>
      <span className="font-mono text-[11px] text-gray-500 truncate py-2">{o.nats_source_subject ?? "—"}</span>
    </button>
  );
});

export function DeadLetterVirtualTable({
  data,
  selectedId,
  onSelect,
}: {
  data: readonly NatsDeadLetterItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}): ReactElement {
  const scrollRef = useRef<HTMLDivElement>(null);

  const columns = useMemo<ColumnDef<NatsDeadLetterItem>[]>(
    () => [
      { accessorKey: "sequence", header: "Seq" },
      { accessorKey: "kind", header: "Kind" },
      { accessorKey: "status_code", header: "HTTP" },
      { accessorKey: "tenant_id", header: "Tenant" },
      { accessorKey: "entity_id", header: "Entity" },
      { accessorKey: "event_type", header: "Event" },
      { accessorKey: "nats_source_subject", header: "Source subject" },
    ],
    [],
  );

  const table = useReactTable({
    data: data as NatsDeadLetterItem[],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => r.id,
  });

  const { rows } = table.getRowModel();
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_PX,
    overscan: 20,
  });

  const headerGroup = table.getHeaderGroups()[0];

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-surface-700 bg-surface-900/40 overflow-hidden">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto overscroll-contain">
        <div
          className={`${GRID_COLS} sticky top-0 z-20 border-b border-surface-700 bg-surface-900 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500`}
        >
          {headerGroup.headers.map((header) => (
            <div key={header.id} className="min-w-0 truncate">
              {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
            </div>
          ))}
        </div>
        <div
          className="relative w-full"
          style={{ height: `${Math.max(virtualizer.getTotalSize(), rows.length ? ROW_HEIGHT_PX : 0)}px` }}
        >
          {virtualizer.getVirtualItems().map((vr) => {
            const row = rows[vr.index];
            if (!row) return null;
            return (
              <VirtualRow
                key={row.id}
                row={row}
                virtualStart={vr.start}
                virtualSize={vr.size}
                selected={selectedId === row.original.id}
                onSelect={onSelect}
              />
            );
          })}
        </div>
      </div>
      <div className="border-t border-surface-700 px-3 py-2 text-[11px] text-gray-500 tabular-nums">
        {rows.length.toLocaleString()} messages peeked (non-destructive)
      </div>
    </div>
  );
}
