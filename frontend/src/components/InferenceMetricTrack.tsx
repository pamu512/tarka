/** 0–1 inference metric with fill bar; risk = higher is worse, trust = higher is better. */

interface InferenceMetricTrackProps {
  label: string;
  value: number;
  variant: "risk" | "trust";
  className?: string;
}

export function InferenceMetricTrack({
  label,
  value,
  variant,
  className = "",
}: InferenceMetricTrackProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const pct = clamped * 100;

  const hint =
    variant === "risk"
      ? "Higher values suggest more risk in this dimension."
      : "Higher values indicate stronger positive signal.";

  const fillGradient =
    variant === "risk"
      ? "linear-gradient(90deg, rgb(34 197 94 / 0.5), rgb(245 158 11 / 0.55), rgb(239 68 68 / 0.65))"
      : "linear-gradient(90deg, rgb(239 68 68 / 0.35), rgb(245 158 11 / 0.45), rgb(34 197 94 / 0.55))";

  return (
    <div className={`space-y-1 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-400">{label}</span>
        <span className="text-xs font-mono text-gray-200 tabular-nums">{clamped.toFixed(2)}</span>
      </div>
      <div className="relative h-2 rounded-full bg-surface-800 border border-surface-600 overflow-hidden">
        <div
          className="absolute top-0 bottom-0 left-0 rounded-full transition-[width] duration-300"
          style={{
            width: `${pct}%`,
            background: fillGradient,
          }}
        />
        <div
          className="absolute top-1/2 w-px h-3 bg-white/70 z-10 -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${pct}%` }}
          aria-hidden
        />
      </div>
      <p className="text-[10px] text-gray-600 leading-snug">{hint}</p>
    </div>
  );
}
