import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useCallback, useMemo, useRef, type ReactElement } from "react";

import type { AuditRecentItem, AuditRuleResult } from "@/api/client";

const ROW_HEIGHT_PX = 36;

const GRID_COLS =
  "grid grid-cols-[minmax(148px,1fr)_minmax(88px,0.55fr)_minmax(220px,1.35fr)_minmax(72px,0.45fr)_40px_minmax(72px,0.45fr)_minmax(56px,0.4fr)] gap-x-3 items-center px-3";

const money = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });

function RuleResultPill({ r }: { r: AuditRuleResult }) {
  const cls =
    r === "DENY"
      ? "bg-rose-500/15 text-rose-200 border-rose-500/35"
      : r === "ALLOW"
        ? "bg-emerald-500/15 text-emerald-200 border-emerald-500/35"
        : r === "SHADOW_REVIEW"
          ? "bg-violet-500/15 text-violet-200 border-violet-500/35"
          : "bg-amber-500/15 text-amber-200 border-amber-500/35";
  return (
    <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${cls}`}>
      {r}
    </span>
  );
}

const VirtualRow = memo(function VirtualRow({
  row,
  virtualStart,
  virtualSize,
}: {
  row: Row<AuditRecentItem>;
  virtualStart: number;
  virtualSize: number;
}): ReactElement {
  return (
    <div
      role="row"
      className={`${GRID_COLS} border-b border-surface-800/90 bg-surface-950/95 text-gray-200 text-[13px] hover:bg-surface-900/80`}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: virtualSize,
        transform: `translateY(${virtualStart}px)`,
      }}
    >
      {row.getVisibleCells().map((cell) => (
        <div key={cell.id} role="cell" className="min-w-0 truncate py-2 tabular-nums">
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </div>
      ))}
    </div>
  );
});

export function AuditLogVirtualTable({
  data,
  loadingMore,
  onScrollNearEnd,
}: {
  data: readonly AuditRecentItem[];
  loadingMore: boolean;
  onScrollNearEnd: () => void;
}): ReactElement {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endFiredRef = useRef(false);

  const columns = useMemo<ColumnDef<AuditRecentItem>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "Time (UTC)",
        cell: (ctx) => {
          const raw = ctx.getValue<string | null>();
          if (!raw) return "—";
          const d = new Date(raw);
          return Number.isFinite(d.getTime()) ? d.toISOString().replace("T", " ").slice(0, 23) : raw;
        },
      },
      {
        accessorKey: "short_id",
        header: "Short",
        cell: (ctx) => <span className="font-mono text-[12px] text-brand-300">{ctx.getValue<string>()}</span>,
      },
      {
        accessorKey: "trace_id",
        header: "Trace",
        cell: (ctx) => (
          <span className="font-mono text-[11px] text-gray-400" title={ctx.getValue<string>()}>
            {ctx.getValue<string>()}
          </span>
        ),
      },
      {
        accessorKey: "amount",
        header: "Amount",
        cell: (ctx) => {
          const row = ctx.row.original;
          const a = row.amount;
          if (a == null) return "—";
          const cur = row.currency ?? "USD";
          return cur === "USD" ? money.format(a) : `${a.toFixed(2)} ${cur}`;
        },
      },
      {
        accessorKey: "currency",
        header: "CCY",
        cell: (ctx) => <span className="text-gray-500">{ctx.getValue<string>() ?? "—"}</span>,
      },
      {
        accessorKey: "rule_result",
        header: "Rule",
        cell: (ctx) => <RuleResultPill r={ctx.getValue<AuditRuleResult>()} />,
      },
      {
        accessorKey: "ai_confidence",
        header: "AI",
        cell: (ctx) => {
          const v = ctx.getValue<number | null>();
          if (v == null) return <span className="text-gray-600">—</span>;
          return <span className="text-gray-300">{(v * 100).toFixed(0)}%</span>;
        },
      },
    ],
    [],
  );

  const table = useReactTable({
    data: data as AuditRecentItem[],
    columns,
    state: {},
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.trace_id,
  });

  const { rows } = table.getRowModel();

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_PX,
    overscan: 32,
  });

  const virtualItems = virtualizer.getVirtualItems();

  const checkEnd = useCallback(() => {
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

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-surface-700 bg-surface-900/40 overflow-hidden">
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto overscroll-contain"
        onScroll={checkEnd}
      >
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
              <VirtualRow key={row.original.trace_id} row={row} virtualStart={vr.start} virtualSize={vr.size} />
            );
          })}
        </div>
      </div>
      <div className="border-t border-surface-700 px-3 py-2 text-[11px] text-gray-500 tabular-nums flex flex-wrap justify-between gap-2">
        <span>
          Buffered <strong className="text-gray-300 font-semibold">{rows.length.toLocaleString()}</strong> rows (virtual
          DOM ~{Math.min(virtualItems.length + 64, rows.length) || 0} nodes)
        </span>
        <span>
          {loadingMore ? (
            <span className="text-amber-400">Loading next page…</span>
          ) : (
            <span className="text-gray-600">Scroll near bottom to stream more</span>
          )}
        </span>
      </div>
    </div>
  );
}
