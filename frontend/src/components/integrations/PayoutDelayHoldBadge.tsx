import type { ReactElement } from "react";

export type PayoutDelayHoldBadgeProps = {
  status: string;
  muleScore?: number | null;
  className?: string;
};

/** Badge for payouts held by JanusGraph mule_score automation (Prompt 183). */
export function PayoutDelayHoldBadge({
  status,
  muleScore,
  className = "",
}: PayoutDelayHoldBadgeProps): ReactElement | null {
  if (status !== "held") return null;

  return (
    <span
      title={
        typeof muleScore === "number"
          ? `Funds held — JanusGraph mule_score ${muleScore}`
          : "Funds held — payout delay automation"
      }
      className={`inline-flex items-center gap-1 rounded border border-violet-500/50 bg-violet-950/35 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-violet-200 ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-violet-400" aria-hidden />
      Payout held
    </span>
  );
}
