/**
 * Compare graph topology frozen at decision/event time vs. the live Janus/Neo4j subgraph.
 */

export type TimeTravelSliderProps = {
  value: number;
  onChange: (value: number) => void;
  /** ISO timestamp for the event-side label (e.g. case creation or trace time). */
  eventTimeIso?: string | null;
  disabled?: boolean;
  snapshotNodeCount: number | null;
  liveNodeCount: number | null;
  className?: string;
};

function formatShort(iso: string | null | undefined): string {
  if (!iso) return "Event";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "Event";
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "Event";
  }
}

export function TimeTravelSlider({
  value,
  onChange,
  eventTimeIso,
  disabled = false,
  snapshotNodeCount,
  liveNodeCount,
  className = "",
}: TimeTravelSliderProps) {
  const atEvent = value < 50;
  const hint = atEvent
    ? `Evidence-locker snapshot (${snapshotNodeCount ?? "—"} nodes)`
    : `Live subgraph (${liveNodeCount ?? "—"} nodes)`;

  return (
    <div
      className={`rounded-xl border border-surface-700 bg-surface-900/90 px-4 py-3 ${className}`}
      data-testid="time-travel-slider"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-200">Time travel</span>
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-surface-800 text-gray-400 border border-surface-600">
            {hint}
          </span>
        </div>
        <span className="text-[11px] text-gray-500 tabular-nums">
          {formatShort(eventTimeIso ?? undefined)} → Now
        </span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-[11px] font-medium text-amber-200/95 w-[5.5rem] shrink-0 leading-tight">
          At event
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-label="Graph time travel: event snapshot versus live graph"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={value}
          aria-valuetext={atEvent ? "Showing graph at event time" : "Showing live graph now"}
          className="flex-1 h-2 accent-brand-500 rounded-full bg-surface-800 disabled:opacity-40 disabled:cursor-not-allowed"
        />
        <span className="text-[11px] font-medium text-emerald-200/95 w-[5.5rem] shrink-0 text-right leading-tight">
          Now
        </span>
      </div>
      <p className="text-[11px] text-gray-500 mt-2 leading-snug">
        Drag past the midpoint to compare frozen evidence topology with the current entity neighborhood (new edges and
        vertices may appear as the graph ingests).
      </p>
    </div>
  );
}
