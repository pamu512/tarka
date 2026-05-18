"use client";

import { useCallback, useState } from "react";
import { Eye, Loader2, Rocket, ShieldAlert, Sparkles } from "lucide-react";

import { BacktestVisualizer } from "@/components/hypothesis/BacktestVisualizer";
import { PromoteToProductionModal } from "@/components/hypothesis/PromoteToProductionModal";
import type { BacktestBlockPoint } from "@/lib/hypothesis/backtestBlockSeries";
import { formatPotentialSavings } from "@/lib/hypothesis/potentialSavings";
import type { HypothesisReport } from "@/types/hypothesis";

export type HypothesisCardObservationState = "idle" | "loading" | "active" | "error";
export type HypothesisCardPromoteState = "idle" | "loading" | "done" | "error";

export type HypothesisCardProps = {
  report: HypothesisReport;
  /** Sum of transaction amounts this rule would have blocked in the backtest window. */
  potentialSavings: number;
  currency?: string;
  className?: string;
  onStartObservation?: (report: HypothesisReport) => void | Promise<void>;
  observationState?: HypothesisCardObservationState;
  observationError?: string | null;
  disabled?: boolean;
  /** Hourly production vs shadow blocks for :class:`BacktestVisualizer` (Prompt 198). */
  backtestBlockSeries?: BacktestBlockPoint[] | null;
  /** Override block-rate uplift shown in the promote guardrail (Prompt 199). */
  estimatedBlockRateImpactPct?: number | null;
  onPromoteToProduction?: (report: HypothesisReport) => void | Promise<void>;
  promoteState?: HypothesisCardPromoteState;
  promoteError?: string | null;
};

function displayNarrative(report: HypothesisReport): string {
  const saarthi = report.saarthi_narrative?.trim();
  if (saarthi) return saarthi;
  return report.narrative?.trim() || "No Saarthi narrative available for this burst.";
}

function fingerprintLabel(kind: HypothesisReport["fingerprint_kind"]): string {
  return kind === "canvas_hash" ? "Canvas hash" : "WebGL vendor";
}

export function HypothesisCard({
  report,
  potentialSavings,
  currency = "USD",
  className = "",
  onStartObservation,
  observationState: controlledObservationState,
  observationError,
  disabled = false,
  backtestBlockSeries,
  estimatedBlockRateImpactPct,
  onPromoteToProduction,
  promoteState: controlledPromoteState,
  promoteError,
}: HypothesisCardProps) {
  const [internalObsState, setInternalObsState] = useState<HypothesisCardObservationState>("idle");
  const [promoteModalOpen, setPromoteModalOpen] = useState(false);
  const [internalPromoteState, setInternalPromoteState] =
    useState<HypothesisCardPromoteState>("idle");
  const [internalPromoteError, setInternalPromoteError] = useState<string | null>(null);
  const observationState = controlledObservationState ?? internalObsState;
  const promoteState = controlledPromoteState ?? internalPromoteState;
  const promoteErrorResolved = promoteError ?? internalPromoteError;
  const savingsLabel = formatPotentialSavings(potentialSavings, currency);
  const narrative = displayNarrative(report);
  const gated = report.analyst_suggestion_allowed !== false;
  const fpr =
    typeof report.backtest_false_positive_rate === "number"
      ? report.backtest_false_positive_rate
      : null;

  const handleStartObservation = useCallback(async () => {
    if (disabled || !onStartObservation) return;
    if (controlledObservationState === undefined) {
      setInternalObsState("loading");
    }
    try {
      await onStartObservation(report);
      if (controlledObservationState === undefined) {
        setInternalObsState("active");
      }
    } catch {
      if (controlledObservationState === undefined) {
        setInternalObsState("error");
      }
    }
  }, [controlledObservationState, disabled, onStartObservation, report]);

  const observationBusy = observationState === "loading";
  const observationActive = observationState === "active";
  const buttonDisabled = disabled || observationBusy || observationActive || !onStartObservation;
  const promoteBusy = promoteState === "loading";
  const promoteDone = promoteState === "done";
  const canPromote =
    observationActive && !disabled && !!onPromoteToProduction && !!report.suggested_rule;

  const handleConfirmPromote = useCallback(
    async (r: HypothesisReport) => {
      if (!onPromoteToProduction) return;
      if (controlledPromoteState === undefined) {
        setInternalPromoteState("loading");
        setInternalPromoteError(null);
      }
      try {
        await onPromoteToProduction(r);
        if (controlledPromoteState === undefined) {
          setInternalPromoteState("done");
        }
        setPromoteModalOpen(false);
      } catch (err) {
        if (controlledPromoteState === undefined) {
          setInternalPromoteState("error");
          setInternalPromoteError(err instanceof Error ? err.message : "Promotion failed");
        }
      }
    },
    [controlledPromoteState, onPromoteToProduction],
  );

  return (
    <article
      className={[
        "flex flex-col overflow-hidden rounded-xl border-2 border-amber-500/55 bg-slate-950 shadow-[0_0_32px_rgba(245,158,11,0.12)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      aria-labelledby={`hypothesis-title-${report.report_id}`}
      data-testid="hypothesis-card"
    >
      <header className="border-b border-amber-500/25 bg-gradient-to-r from-amber-950/80 via-slate-950 to-slate-950 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <ShieldAlert className="size-4 shrink-0 text-amber-400" aria-hidden />
            <h2
              id={`hypothesis-title-${report.report_id}`}
              className="text-[11px] font-bold uppercase tracking-[0.2em] text-amber-200"
            >
              Hypothesis
            </h2>
            {!gated ? (
              <span className="rounded border border-red-500/70 bg-red-950/90 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-100">
                Backtest blocked
              </span>
            ) : null}
          </div>
          <p className="max-w-full truncate text-[10px] font-medium uppercase tracking-wider text-slate-500">
            {fingerprintLabel(report.fingerprint_kind)} · {report.distinct_account_count} accounts
          </p>
        </div>
      </header>

      <div className="grid gap-0 lg:grid-cols-[1fr_minmax(12rem,16rem)]">
        <section className="border-b border-slate-800/90 px-4 py-4 lg:border-b-0 lg:border-r lg:border-slate-800/90">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-violet-300/95">
            <Sparkles className="size-3.5 shrink-0" aria-hidden />
            Saarthi narrative
          </div>
          <p
            className="text-base font-medium leading-relaxed text-white sm:text-lg"
            data-testid="hypothesis-saarthi-narrative"
          >
            {narrative}
          </p>
          {fpr !== null ? (
            <p className="mt-3 font-mono text-[11px] text-slate-500">
              7-day backtest FPR: {(fpr * 100).toFixed(3)}%
            </p>
          ) : null}
        </section>

        <section
          className="flex flex-col justify-between bg-amber-950/25 px-4 py-4"
          aria-label="Potential savings impact"
        >
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-amber-300/90">
              Potential savings
            </p>
            <p
              className="mt-1 text-3xl font-extrabold tabular-nums tracking-tight text-amber-100 sm:text-4xl"
              data-testid="hypothesis-potential-savings"
            >
              {savingsLabel}
            </p>
            <p className="mt-1 text-[11px] leading-snug text-amber-200/75">
              Estimated value of transactions this rule would have blocked.
            </p>
          </div>
        </section>
      </div>

      <footer className="border-t border-slate-800/90 bg-slate-900/50 px-4 py-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[11px] text-slate-500">
            Shadow observation records matches without changing live decisions.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void handleStartObservation()}
              disabled={buttonDisabled}
              className={[
                "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-bold uppercase tracking-wide transition-colors",
                observationActive
                  ? "border border-emerald-600/80 bg-emerald-950/80 text-emerald-200"
                  : "border-2 border-white bg-white text-slate-950 hover:bg-amber-50 disabled:border-slate-600 disabled:bg-slate-800 disabled:text-slate-500",
              ].join(" ")}
              data-testid="hypothesis-start-observation"
            >
              {observationBusy ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Eye className="size-4 shrink-0" aria-hidden />
              )}
              {observationActive ? "Observation active" : "Start observation"}
            </button>
            {canPromote ? (
              <button
                type="button"
                onClick={() => setPromoteModalOpen(true)}
                disabled={promoteBusy || promoteDone}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border-2 border-amber-400 bg-amber-500 px-4 py-2.5 text-sm font-bold uppercase tracking-wide text-slate-950 hover:bg-amber-400 disabled:opacity-50"
                data-testid="hypothesis-promote"
              >
                {promoteBusy ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Rocket className="size-4 shrink-0" aria-hidden />
                )}
                {promoteDone ? "Promoted" : "Promote"}
              </button>
            ) : null}
          </div>
        </div>
        {observationError ? (
          <p className="mt-2 text-xs text-red-400" role="alert">
            {observationError}
          </p>
        ) : null}
      </footer>

      {backtestBlockSeries && backtestBlockSeries.length > 0 ? (
        <div className="border-t border-slate-800/90 bg-slate-900/30 px-4 py-4">
          <BacktestVisualizer
            series={backtestBlockSeries}
            lookbackDays={report.backtest_lookback_days ?? 7}
          />
        </div>
      ) : null}

      <PromoteToProductionModal
        open={promoteModalOpen}
        report={report}
        backtestBlockSeries={backtestBlockSeries}
        estimatedBlockRateImpactPct={estimatedBlockRateImpactPct}
        onClose={() => setPromoteModalOpen(false)}
        onConfirmPromote={handleConfirmPromote}
        promoteState={promoteState}
        promoteError={promoteErrorResolved}
      />
    </article>
  );
}
