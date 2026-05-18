import { useMemo } from "react";
import type { InferenceContext } from "../../api/inferenceContext";
import { buildVelocityHeatmapModel } from "../../utils/velocityHeatmapModel";

type Props = {
  inference: InferenceContext | null;
  /** Case / audit timestamp — anchors inferred hourly shape to business “now” when buckets are omitted. */
  anchorIso?: string | null;
  className?: string;
};

function intensityClasses(count: number, max: number, isPeak: boolean): string {
  if (max <= 0 || count <= 0) {
    return isPeak
      ? "bg-surface-800 border border-brand-500/40"
      : "bg-surface-900/90 border border-surface-700/80";
  }
  const t = count / max;
  if (t >= 0.85) {
    return "bg-rose-600/85 border border-rose-400/60 text-white";
  }
  if (t >= 0.55) {
    return "bg-amber-600/75 border border-amber-400/45 text-amber-50";
  }
  if (t >= 0.25) {
    return "bg-amber-900/55 border border-amber-700/35 text-amber-100/95";
  }
  return "bg-surface-800 border border-surface-600/70 text-gray-300";
}

/** 24-column UTC heatmap of event velocity — shows where the burst clusters (Prompt 159). */
export function VelocityHeatmap({ inference, anchorIso, className = "" }: Props) {
  const model = useMemo(
    () => buildVelocityHeatmapModel(inference, anchorIso ?? null),
    [inference, anchorIso],
  );

  if (!inference || !model) {
    return null;
  }

  const max = Math.max(...model.buckets, 1);
  const peak = model.peakHourUtc;

  return (
    <section
      className={`rounded-xl border border-surface-700 bg-surface-900/80 px-4 py-3 space-y-2 ${className}`}
      aria-label="Velocity heatmap, UTC hours"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Velocity heatmap</h3>
          <p className="text-[11px] text-gray-500 mt-0.5">
            Rolling 24h activity by UTC hour
            {model.synthesized ? (
              <span className="text-gray-600">
                {" "}
                — shape inferred from 5m / 1h / 24h counters when hourly buckets are unavailable.
              </span>
            ) : null}
          </p>
        </div>
        {peak != null && model.total > 0 ? (
          <span className="text-[11px] font-mono text-brand-300/95 tabular-nums">
            Peak UTC hour {String(peak).padStart(2, "0")}:00 · {model.buckets[peak]} events
          </span>
        ) : (
          <span className="text-[11px] text-gray-500">No burst in window</span>
        )}
      </div>

      {model.total <= 0 ? (
        <p className="text-xs text-gray-500 py-2">No velocity events recorded in the last 24 hours.</p>
      ) : (
        <>
          <div
            className="grid gap-1 w-full min-h-[52px]"
            style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}
            role="group"
          >
            {model.buckets.map((count, hour) => {
              const isPeak = peak === hour;
              return (
                <div
                  key={hour}
                  title={`${String(hour).padStart(2, "0")}:00 UTC — ${count} events`}
                  className={`rounded-sm min-h-[40px] flex flex-col items-center justify-center text-[10px] font-mono tabular-nums leading-none px-0.5 py-1 transition-colors ${intensityClasses(count, max, isPeak)}`}
                  aria-label={`Hour ${hour} UTC, ${count} events`}
                >
                  <span className="opacity-90">{count > 0 ? (count > 99 ? "99+" : count) : ""}</span>
                </div>
              );
            })}
          </div>
          <div
            className="flex justify-between text-[10px] text-gray-600 font-mono tabular-nums px-0.5 pt-1 border-t border-surface-800"
            aria-hidden
          >
            <span>00</span>
            <span>06</span>
            <span>12</span>
            <span>18</span>
            <span>23</span>
          </div>
        </>
      )}
    </section>
  );
}
