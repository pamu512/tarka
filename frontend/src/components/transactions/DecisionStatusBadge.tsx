import { memo, type ReactElement } from "react";

import type { DecisionSurface } from "@/domain/transactionRow";
import { cn } from "@/lib/utils";

const STYLES: Record<DecisionSurface, string> = {
  Block: "bg-red-500/15 text-red-300 border-red-500/40",
  Allow: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  Challenge: "bg-amber-500/15 text-amber-200 border-amber-500/40",
};

export const DecisionStatusBadge = memo(function DecisionStatusBadge({
  status,
  className,
}: {
  status: DecisionSurface;
  className?: string;
}): ReactElement {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide tabular-nums",
        STYLES[status],
        className,
      )}
    >
      {status}
    </span>
  );
});
