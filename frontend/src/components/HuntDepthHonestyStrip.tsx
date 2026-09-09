import type { HuntDepthHonesty } from "../domain/huntDepthHonesty";

export function HuntDepthHonestyStrip({ honesty }: { honesty: HuntDepthHonesty }) {
  const tone = honesty.planeOff || honesty.degraded
    ? "border-amber-500/35 bg-amber-500/10 text-amber-100/90"
    : "border-surface-600 bg-surface-900/80 text-gray-300";
  return (
    <p
      data-testid="hunt-depth-honesty"
      role="status"
      className={`text-xs rounded-lg border px-3 py-2 ${tone}`}
    >
      {honesty.degraded ? (
        <span className="mr-2 inline-block rounded-full border border-amber-400/40 px-2 py-0.5 text-[10px] uppercase tracking-wide">
          Depth capped
        </span>
      ) : null}
      {honesty.banner}
    </p>
  );
}
