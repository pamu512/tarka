import { useCallback, useRef, useState } from "react";

import { postOrchestratorSimulateAttack } from "@/api/orchestratorSimulateAttack";
import { cn } from "@/lib/utils";
import { useToast } from "@/context/ToastContext";
import { toUserFacingError } from "@/utils/userFacingErrors";

const MARQUEE_STYLE = `
@keyframes control-panel-marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.cp-marquee-track {
  display: inline-flex;
  width: max-content;
  animation: control-panel-marquee 14s linear infinite;
}
`;

export type ControlPanelProps = {
  /** Override orchestrator URL (defaults to Vite proxy ``/api/v1/demo/simulate_attack``). */
  simulateAttackUrl?: string;
  className?: string;
};

/**
 * Demo control strip: triggers orchestrator ``POST /v1/demo/simulate_attack``.
 * Button stays disabled until the **full** result array has been received (no request overlap).
 */
export function ControlPanel({ simulateAttackUrl, className }: ControlPanelProps) {
  const { toast } = useToast();
  const [running, setRunning] = useState(false);
  const inFlightRef = useRef(false);

  const onTrigger = useCallback(async () => {
    if (inFlightRef.current || running) return;
    inFlightRef.current = true;
    setRunning(true);
    try {
      const { results } = await postOrchestratorSimulateAttack(simulateAttackUrl);
      toast(`Simulation complete (${results.length} outcomes)`, "success");
    } catch (e) {
      toast(toUserFacingError(e, { subject: "Simulation", action: "run simulate_attack" }), "error");
    } finally {
      setRunning(false);
      inFlightRef.current = false;
    }
  }, [simulateAttackUrl, toast]);

  const label = "Live Attack in Progress";
  const marqueeText = `${label} · ${label} · `;

  return (
    <div className={cn("rounded-xl border border-surface-700 bg-surface-900/80 p-4", className)}>
      <style>{MARQUEE_STYLE}</style>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-200">Control panel</h2>
          <p className="text-[11px] text-gray-500 font-mono mt-0.5">POST /v1/demo/simulate_attack</p>
        </div>
        <button
          type="button"
          disabled={running}
          aria-busy={running}
          onClick={() => void onTrigger()}
          className={cn(
            "shrink-0 rounded-lg border border-brand-600/70 bg-brand-950/40 px-4 py-2 text-sm font-semibold text-brand-100",
            "hover:bg-brand-900/50 disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          Trigger Simulation
        </button>
      </div>

      {running ? (
        <div
          className="mt-3 overflow-hidden rounded-md border border-amber-600/35 bg-amber-950/20 py-2"
          aria-live="polite"
          aria-label="Live attack in progress"
        >
          <div className="cp-marquee-track whitespace-nowrap px-2 text-xs font-semibold uppercase tracking-widest text-amber-200/95">
            <span>{marqueeText}</span>
            <span aria-hidden="true">{marqueeText}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
