import type { ReactElement } from "react";

export type RegionalRiskBlacklistBadgeProps = {
  label?: string;
  className?: string;
};

/** Badge for transactions or entities in a blacklisted sub-region (Prompt 187). */
export function RegionalRiskBlacklistBadge({
  label,
  className = "",
}: RegionalRiskBlacklistBadgeProps): ReactElement {
  return (
    <span
      title={label ? `Blacklisted sub-region: ${label}` : "Sub-region blacklisted — attack wave policy"}
      className={`inline-flex items-center gap-1 rounded border border-rose-500/50 bg-rose-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-rose-200 ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-rose-400" aria-hidden />
      Region blocked
    </span>
  );
}
