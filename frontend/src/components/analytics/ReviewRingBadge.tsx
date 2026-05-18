import type { ReactElement } from "react";

export type ReviewRingBadgeProps = {
  memberCount?: number;
  className?: string;
};

/** Badge for users in a coordinated five-product review ring (Prompt 185). */
export function ReviewRingBadge({ memberCount, className = "" }: ReviewRingBadgeProps): ReactElement {
  const title =
    memberCount != null
      ? `Review ring — ${memberCount} users reviewed the same 5 products`
      : "Review ring — identical 5-product review overlap";

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded border border-cyan-500/45 bg-cyan-950/35 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-cyan-200 ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" aria-hidden />
      Review ring
    </span>
  );
}
