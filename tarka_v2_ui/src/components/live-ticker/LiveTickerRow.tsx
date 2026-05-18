import { memo } from "react";
import { StatusBadge } from "@/components/live-ticker/StatusBadge";
import type { AuditRecentItem } from "@/types/audit-recent";

export type LiveTickerRowProps = Pick<
  AuditRecentItem,
  "timestamp" | "transaction_id" | "amount_cents" | "status"
> & {
  onSelect?: (transactionId: string) => void;
};

function formatAmount(cents: number): string {
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const formatted = (abs / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return negative ? `−$${formatted}` : `$${formatted}`;
}

function truncateTxnId(id: string): string {
  if (id.length <= 20) return id;
  return `${id.slice(0, 14)}…${id.slice(-5)}`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export const LiveTickerRow = memo(function LiveTickerRow({
  timestamp,
  transaction_id,
  amount_cents,
  status,
  onSelect,
}: LiveTickerRowProps) {
  const interactive = typeof onSelect === "function";

  return (
    <tr
      className={`h-10 border-b border-slate-800/60 ${
        interactive
          ? "cursor-pointer hover:bg-slate-900/50 focus-visible:bg-slate-900/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-purple-600/80"
          : ""
      }`}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? () => onSelect(transaction_id) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(transaction_id);
              }
            }
          : undefined
      }
      aria-label={interactive ? `Open decision detail for ${transaction_id}` : undefined}
    >
      <td className="whitespace-nowrap px-4 py-2 tabular-nums text-slate-400">
        {formatTimestamp(timestamp)}
      </td>
      <td
        className="max-w-0 truncate px-4 py-2 font-mono text-slate-300"
        title={transaction_id}
      >
        {truncateTxnId(transaction_id)}
      </td>
      <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-slate-200">
        {formatAmount(amount_cents)}
      </td>
      <td className="px-4 py-2">
        <StatusBadge status={status} />
      </td>
    </tr>
  );
});
