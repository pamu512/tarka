/** Horizontal 0–100 fraud score with zone shading and a position marker (cold-user context). */

interface FraudScoreTrackProps {
  score: number;
  className?: string;
}

export function FraudScoreTrack({ score, className = "" }: FraudScoreTrackProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const pct = clamped;

  let band: string;
  if (clamped >= 80) band = "Critical — strong fraud signals";
  else if (clamped >= 60) band = "High — likely review or block";
  else if (clamped >= 40) band = "Elevated — consider review";
  else if (clamped >= 20) band = "Moderate — monitor";
  else band = "Lower band — fewer elevated signals";

  return (
    <div className={`space-y-1.5 ${className}`}>
      <div className="relative h-3 rounded-full overflow-hidden bg-surface-800 border border-surface-600">
        {/* Zone legend as background gradient: low (left) → high (right) concern */}
        <div
          className="absolute inset-y-0 left-0 right-0 opacity-90"
          style={{
            background:
              "linear-gradient(90deg, rgb(6 182 212 / 0.35) 0%, rgb(34 197 94 / 0.35) 18%, rgb(245 158 11 / 0.4) 45%, rgb(249 115 22 / 0.45) 72%, rgb(239 68 68 / 0.5) 100%)",
          }}
        />
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.4)] z-10 rounded-full -translate-x-1/2"
          style={{ left: `${pct}%` }}
          title={`Score ${clamped.toFixed(0)}`}
        />
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[11px]">
        <span className="text-gray-500">
          0 <span className="text-gray-600">lower concern</span>
          <span className="mx-1.5 text-surface-600">·</span>
          <span className="text-gray-600">higher concern</span> 100
        </span>
        <span className="text-gray-300 font-medium">{band}</span>
      </div>
    </div>
  );
}
