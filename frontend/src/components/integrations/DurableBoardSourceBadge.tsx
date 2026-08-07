import type { ReactElement } from "react";

export type DurableBoardSourceBadgeProps = {
  source?: string | null;
  recordCount?: number;
  className?: string;
};

/**
 * Honesty badge for lean marketplace boards backed by durable ingress stores.
 * Empty tenant ≠ SHA demo aggregates.
 */
export function DurableBoardSourceBadge({
  source,
  recordCount,
  className = "",
}: DurableBoardSourceBadgeProps): ReactElement | null {
  const src = (source || "").trim().toLowerCase();
  if (!src && recordCount == null) return null;

  const isDurable = src.startsWith("durable");
  const isMock = src === "mock" || src.startsWith("demo");
  const empty = typeof recordCount === "number" && recordCount === 0;

  let label = src || "unknown";
  let tone = "border-surface-600 bg-surface-800/80 text-gray-300";
  if (src === "durable+automation" || src.includes("automation")) {
    label = "Durable · automation";
    tone = "border-emerald-500/40 bg-emerald-950/30 text-emerald-200";
  } else if (isDurable) {
    label = "Durable records";
    tone = "border-emerald-500/40 bg-emerald-950/30 text-emerald-200";
  } else if (isMock) {
    label = "Demo / mock";
    tone = "border-amber-500/40 bg-amber-950/25 text-amber-200";
  }

  return (
    <div className={`space-y-1.5 ${className}`} data-testid="durable-board-source">
      <span
        className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}
        title={`Board source=${source ?? "unset"}`}
      >
        {label}
      </span>
      {empty && isDurable ? (
        <p className="text-[11px] text-gray-500 leading-snug" data-testid="durable-board-empty-callout">
          No tenant records yet — empty board, not demo SHA aggregates.
        </p>
      ) : null}
    </div>
  );
}
