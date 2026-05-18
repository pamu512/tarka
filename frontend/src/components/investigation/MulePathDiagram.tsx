import { useMemo, type ReactElement } from "react";

import type { MulePathHop, MulePathTransfer } from "@/api/client";

const ROLE_STYLES: Record<string, { ring: string; fill: string; badge: string }> = {
  origin: {
    ring: "border-sky-500/50",
    fill: "bg-sky-950/40",
    badge: "text-sky-300 border-sky-500/40",
  },
  mule: {
    ring: "border-amber-500/55",
    fill: "bg-amber-950/35",
    badge: "text-amber-200 border-amber-500/45",
  },
  payout: {
    ring: "border-rose-500/50",
    fill: "bg-rose-950/30",
    badge: "text-rose-200 border-rose-500/40",
  },
};

function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency || "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

export type MulePathDiagramProps = {
  hops: MulePathHop[];
  transfers: MulePathTransfer[];
  currency: string;
  selectedHopIndex: number;
  onSelectHop: (index: number) => void;
};

export function MulePathDiagram({
  hops,
  transfers,
  currency,
  selectedHopIndex,
  onSelectHop,
}: MulePathDiagramProps): ReactElement {
  const transferByLeg = useMemo(() => {
    const m = new Map<string, MulePathTransfer>();
    for (const t of transfers) {
      m.set(`${t.from_role}->${t.to_role}`, t);
    }
    return m;
  }, [transfers]);

  return (
    <div className="w-full overflow-x-auto pb-2">
      <div className="min-w-[720px] flex items-stretch justify-between gap-2 px-2 py-6">
        {hops.map((hop, idx) => {
          const style = ROLE_STYLES[hop.role] ?? ROLE_STYLES.origin;
          const nextHop = hops[idx + 1];
          const xfer = nextHop
            ? transferByLeg.get(`${hop.role}->${nextHop.role}`)
            : undefined;
          const selected = selectedHopIndex === idx;

          return (
            <div key={hop.entity_id} className="flex items-center flex-1 min-w-0">
              <button
                type="button"
                onClick={() => onSelectHop(idx)}
                className={`flex-1 min-w-[160px] max-w-[220px] rounded-xl border-2 p-4 text-left transition-shadow ${
                  style.ring
                } ${style.fill} ${selected ? "ring-2 ring-brand-400/60 shadow-lg shadow-brand-900/20" : ""}`}
              >
                <span
                  className={`inline-block text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border mb-2 ${style.badge}`}
                >
                  {hop.role === "origin" ? "User A" : hop.role === "mule" ? "User B · Mule" : "Payout"}
                </span>
                <p className="text-sm font-semibold text-gray-100 truncate" title={hop.label}>
                  {hop.label}
                </p>
                <p className="text-[11px] font-mono text-gray-500 mt-1 truncate">{hop.entity_id}</p>
                {hop.account_id ? (
                  <p className="text-[10px] text-gray-600 mt-1 truncate">{hop.account_id}</p>
                ) : null}
              </button>

              {xfer ? (
                <div className="flex flex-col items-center justify-center px-2 shrink-0 w-[120px]">
                  <svg width="100" height="24" className="text-surface-600" aria-hidden>
                    <defs>
                      <marker id={`arrow-${idx}`} markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                        <polygon points="0 0, 8 4, 0 8" fill="currentColor" className="text-brand-400" />
                      </marker>
                    </defs>
                    <line
                      x1="4"
                      y1="12"
                      x2="88"
                      y2="12"
                      stroke="currentColor"
                      strokeWidth="2"
                      markerEnd={`url(#arrow-${idx})`}
                      className="text-brand-500/70"
                    />
                  </svg>
                  <p className="text-xs font-semibold text-brand-200 tabular-nums mt-1">
                    {formatMoney(xfer.amount, xfer.currency || currency)}
                  </p>
                  <p className="text-[10px] text-gray-600 font-mono truncate max-w-full" title={xfer.trace_id}>
                    {xfer.trace_id}
                  </p>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
