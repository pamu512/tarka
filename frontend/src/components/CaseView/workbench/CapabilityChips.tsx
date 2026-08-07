import type { CapabilityState, CapabilityStatus } from "../../../workbench/capabilityStatus";

const ENTRIES: Array<{ key: keyof CapabilityStatus; label: string }> = [
  { key: "audit", label: "Decision audit" },
  { key: "graph", label: "Graph" },
  { key: "calibration", label: "Calibration" },
];

function chipClass(state: CapabilityState): string {
  if (state === "ok") return "border-emerald-500/35 bg-emerald-500/10 text-emerald-300/90";
  if (state === "down") return "border-amber-500/40 bg-amber-500/10 text-amber-200";
  return "border-surface-600 bg-surface-900 text-gray-500";
}

function chipWord(state: CapabilityState): string {
  if (state === "ok") return "ok";
  if (state === "down") return "down";
  return "n/a";
}

type CapabilityChipsProps = {
  status: CapabilityStatus;
  calibrationHint?: string | null;
};

/** Fail-closed capability strip — operators see what they can still trust. */
export function CapabilityChips({ status, calibrationHint }: CapabilityChipsProps) {
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="status"
      aria-label="Workbench capability status"
    >
      {ENTRIES.map(({ key, label }) => {
        const state = status[key];
        const hint =
          key === "calibration" && calibrationHint && state === "ok"
            ? ` — ${calibrationHint}`
            : state === "down"
              ? " — unavailable"
              : "";
        return (
          <span
            key={key}
            className={`text-[10px] uppercase tracking-wide font-medium px-2 py-0.5 rounded border ${chipClass(state)}`}
            title={`${label}: ${chipWord(state)}${hint}`}
          >
            {label}: {chipWord(state)}
          </span>
        );
      })}
    </div>
  );
}
