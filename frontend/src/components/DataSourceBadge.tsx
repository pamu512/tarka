import { useEffect, useState } from "react";
import { getDataSourceSnapshot, subscribeDataSource, type DataOutcome } from "../api/dataSourceState";

function labelFor(outcome: DataOutcome): { text: string; className: string } {
  switch (outcome) {
    case "live":
      return {
        text: "Live API",
        className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
      };
    case "mock":
      return {
        text: "Demo data",
        className: "bg-amber-500/15 text-amber-300 border-amber-500/35",
      };
    case "offline":
      return {
        text: "Offline",
        className: "bg-red-500/15 text-red-400 border-red-500/30",
      };
    default:
      return { text: "Unknown", className: "bg-surface-700 text-gray-400 border-surface-600" };
  }
}

export function DataSourceBadge() {
  const [snap, setSnap] = useState(() => getDataSourceSnapshot());

  useEffect(() => subscribeDataSource(() => setSnap(getDataSourceSnapshot())), []);

  const { text, className } = labelFor(snap.outcome);
  const ago = formatAgo(snap.updatedAt);

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold shrink-0 ${className}`}
      title={`Last request: ${snap.outcome}. ${ago}`}
    >
      <span className="tabular-nums">{text}</span>
      <span className="font-normal opacity-80 hidden sm:inline">· {ago}</span>
    </span>
  );
}

function formatAgo(ts: number) {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}
