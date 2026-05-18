import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useCallback, useMemo, useRef, type ReactElement } from "react";

import type { DecisionSurface, TransactionRow } from "@/domain/transactionRow";

import { DecisionStatusBadge } from "./DecisionStatusBadge";

const ROW_HEIGHT_PX = 36;

const GRID_COLS =
  "grid grid-cols-[44px_minmax(152px,1.1fr)_minmax(168px,1.2fr)_minmax(168px,1.2fr)_minmax(112px,0.9fr)_minmax(104px,0.8fr)_72px_128px] gap-x-3 items-center px-3";

const money = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });

function formatMoney(cents: number, currency: string): string {
  if (currency === "USD") {
    return money.format(cents / 100);
  }
  return `${(cents / 100).toFixed(2)} ${currency}`;
}

const VirtualTableRow = memo(function VirtualTableRow({
  row,
  virtualStart,
  virtualSize,
  compareSelected,
  onToggleCompare,
}: {
  row: Row<TransactionRow>;
  virtualStart: number;
  virtualSize: number;
  compareSelected: boolean;
  onToggleCompare: (id: string) => void;
}): ReactElement {
  const id = row.original.id;
  return (
    <div
      role="row"
      className={`${GRID_COLS} border-b border-surface-800/90 bg-surface-950/95 text-gray-200 text-[13px] hover:bg-surface-900/80 ${
        compareSelected ? "bg-emerald-950/25 ring-1 ring-inset ring-emerald-500/20" : ""
      }`}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: virtualSize,
        transform: `translateY(${virtualStart}px)`,
      }}
    >
      <div
        role="cell"
        className="flex items-center justify-center py-2"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          type="checkbox"
          checked={compareSelected}
          onChange={() => onToggleCompare(id)}
          className="accent-emerald-500 h-4 w-4 cursor-pointer"
          aria-label={`Select transaction ${id} for hardware diff`}
        />
      </div>
      {row.getVisibleCells().map((cell) => (
        <div key={cell.id} role="cell" className="min-w-0 truncate py-2 tabular-nums">
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </div>
      ))}
    </div>
  );
});

export function TransactionVirtualTable({
  data,
  compareIds,
  onToggleCompare,
  loadingMore = false,
  onScrollNearEnd,
  footerExtra,
}: {
  data: readonly TransactionRow[];
  /** Up to two row ids selected for visual hardware diff. */
  compareIds: readonly string[];
  onToggleCompare: (rowId: string) => void;
  loadingMore?: boolean;
  onScrollNearEnd?: () => void;
  footerExtra?: React.ReactNode;
}): ReactElement {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endFiredRef = useRef(false);

  const columns = useMemo<ColumnDef<TransactionRow>[]>(
    () => [
      {
        accessorKey: "timestamp",
        header: "Time (UTC)",
        cell: (ctx) => {
          const v = ctx.getValue<string>();
          const d = new Date(v);
          return Number.isFinite(d.getTime()) ? d.toISOString().replace("T", " ").slice(0, 23) : v;
        },
        size: 180,
      },
      {
        accessorKey: "traceId",
        header: "Trace",
        cell: (ctx) => <span className="font-mono text-[12px] text-gray-300">{ctx.getValue<string>()}</span>,
        size: 200,
      },
      {
        accessorKey: "entityId",
        header: "Entity",
        cell: (ctx) => <span className="font-mono text-[12px] text-gray-300">{ctx.getValue<string>()}</span>,
        size: 200,
      },
      {
        accessorKey: "channel",
        header: "Channel",
        cell: (ctx) => <span className="text-gray-400">{ctx.getValue<string>()}</span>,
        size: 120,
      },
      {
        accessorKey: "amountCents",
        header: "Amount",
        cell: (ctx) => {
          const row = ctx.row.original;
          return <span>{formatMoney(row.amountCents, row.currency)}</span>;
        },
        size: 120,
      },
      {
        accessorKey: "currency",
        header: "CCY",
        cell: (ctx) => <span className="text-gray-500">{ctx.getValue<string>()}</span>,
        size: 72,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (ctx) => <DecisionStatusBadge status={ctx.getValue<DecisionSurface>()} />,
        size: 128,
      },
    ],
    [],
  );

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table; row virtualization keeps DOM small
  const table = useReactTable({
    data: data as TransactionRow[],
    columns,
    state: {},
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => r.id,
  });

  const { rows } = table.getRowModel();

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_PX,
    overscan: 24,
  });

  const virtualItems = virtualizer.getVirtualItems();

  const checkEnd = useCallback(() => {
    if (!onScrollNearEnd) return;
    const el = scrollRef.current;
    if (!el || rows.length === 0) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 420;
    if (nearBottom && !endFiredRef.current) {
      endFiredRef.current = true;
      onScrollNearEnd();
      window.setTimeout(() => {
        endFiredRef.current = false;
      }, 400);
    }
  }, [onScrollNearEnd, rows.length]);

  const headerGroup = table.getHeaderGroups()[0];
  const compareSet = useMemo(() => new Set(compareIds), [compareIds]);

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-surface-700 bg-surface-900/40 overflow-hidden">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto overscroll-contain" onScroll={checkEnd}>
        <div
          className={`${GRID_COLS} sticky top-0 z-20 border-b border-surface-700 bg-surface-900 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500`}
        >
          <div className="min-w-0 text-center" title="Pick two rows for hardware signal diff">
            Diff
          </div>
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
            if (!row) {
              return null;
            }
            return (
              <VirtualTableRow
                key={row.id}
                row={row}
                virtualStart={vr.start}
                virtualSize={vr.size}
                compareSelected={compareSet.has(row.original.id)}
                onToggleCompare={onToggleCompare}
              />
            );
          })}
        </div>
      </div>
      <div className="border-t border-surface-700 px-3 py-2 text-[11px] text-gray-500 tabular-nums flex flex-wrap justify-between gap-2">
        <span>
          Buffered <strong className="text-gray-300 font-semibold">{rows.length.toLocaleString()}</strong> rows
          {footerExtra}
        </span>
        <span>
          {loadingMore ? (
            <span className="text-amber-400">Loading next DuckDB page…</span>
          ) : onScrollNearEnd ? (
            <span className="text-gray-600">Scroll near bottom to load more</span>
          ) : (
            <span>
              Row height {ROW_HEIGHT_PX}px · virtual DOM ~{Math.min(virtualItems.length + 64, rows.length) || 0}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
