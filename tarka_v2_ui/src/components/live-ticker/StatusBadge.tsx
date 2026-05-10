import { memo } from "react";
import type { AuditRecentStatus } from "@/types/audit-recent";

type StatusBadgeProps = {
  status: AuditRecentStatus;
};

const BADGE_BY_STATUS: Record<AuditRecentStatus, string> = {
  BLOCK: "bg-red-950/90 text-red-300 ring-1 ring-red-800/80",
  FLAG: "bg-yellow-950/90 text-yellow-300 ring-1 ring-yellow-800/80",
  SHADOW_REVIEW: "bg-purple-950/90 text-purple-300 ring-1 ring-purple-800/80",
  ALLOW: "bg-emerald-950/90 text-emerald-300 ring-1 ring-emerald-800/80",
};

export const StatusBadge = memo(function StatusBadge({ status }: StatusBadgeProps) {
  const label = status.replaceAll("_", " ");

  return (
    <span
      className={`inline-flex max-w-full items-center rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${BADGE_BY_STATUS[status]}`}
    >
      {label}
    </span>
  );
});
