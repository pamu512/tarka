"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { AlertTriangle, ArrowLeft, Loader2, ShieldCheck } from "lucide-react";

import {
  buildPromotionSummaryText,
  estimateBlockRateImpactPct,
  formatRuleLabel,
  type PromotionSummaryInput,
} from "@/lib/hypothesis/promotionImpact";
import type { BacktestBlockPoint } from "@/lib/hypothesis/backtestBlockSeries";
import type { HypothesisReport } from "@/types/hypothesis";

export type PromoteModalStep = "review" | "confirm";

export type PromoteToProductionModalProps = {
  open: boolean;
  report: HypothesisReport;
  backtestBlockSeries?: BacktestBlockPoint[] | null;
  /** Override computed block-rate uplift (e.g. from ops model). */
  estimatedBlockRateImpactPct?: number | null;
  onClose: () => void;
  onConfirmPromote: (report: HypothesisReport) => void | Promise<void>;
  promoteState?: "idle" | "loading" | "done" | "error";
  promoteError?: string | null;
};

export function PromoteToProductionModal({
  open,
  report,
  backtestBlockSeries,
  estimatedBlockRateImpactPct: impactOverride,
  onClose,
  onConfirmPromote,
  promoteState = "idle",
  promoteError,
}: PromoteToProductionModalProps) {
  const titleId = useId();
  const [step, setStep] = useState<PromoteModalStep>("review");

  const rule = report.suggested_rule ?? null;
  const ruleLabel = formatRuleLabel(rule);
  const impactPct = estimateBlockRateImpactPct(backtestBlockSeries, impactOverride);
  const summaryInput: PromotionSummaryInput = { ruleLabel, estimatedBlockRateImpactPct: impactPct };
  const finalSummary = buildPromotionSummaryText(summaryInput);

  useEffect(() => {
    if (!open) {
      setStep("review");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && promoteState !== "loading") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, promoteState]);

  const handleBackdrop = useCallback(() => {
    if (promoteState !== "loading") onClose();
  }, [onClose, promoteState]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      role="presentation"
      onClick={handleBackdrop}
      data-testid="promote-modal-backdrop"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-lg rounded-xl border-2 border-amber-500/50 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="promote-to-production-modal"
      >
        <header className="border-b border-slate-800 px-5 py-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-400" aria-hidden />
            <div>
              <h2 id={titleId} className="text-base font-bold text-white">
                {step === "review" ? "Promote to production" : "Confirm promotion"}
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Step {step === "review" ? "1" : "2"} of 2 — guardrail before going live
              </p>
            </div>
          </div>
        </header>

        <div className="px-5 py-4 space-y-4">
          {step === "review" ? (
            <>
              <p className="text-sm leading-relaxed text-slate-300">
                You are about to move a shadow observation rule into the active policy path. Live
                traffic will be evaluated against this rule; blocks and reviews will affect customers.
              </p>
              <dl className="grid grid-cols-2 gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-xs">
                <div>
                  <dt className="text-slate-500 uppercase tracking-wide">Rule</dt>
                  <dd className="mt-1 font-mono text-lg font-bold text-amber-100">{ruleLabel}</dd>
                </div>
                <div>
                  <dt className="text-slate-500 uppercase tracking-wide">Current mode</dt>
                  <dd className="mt-1 font-semibold text-amber-300">Observation</dd>
                </div>
                <div>
                  <dt className="text-slate-500 uppercase tracking-wide">Target mode</dt>
                  <dd className="mt-1 font-semibold text-emerald-300">Active</dd>
                </div>
                <div>
                  <dt className="text-slate-500 uppercase tracking-wide">Est. block-rate Δ</dt>
                  <dd className="mt-1 font-mono text-lg font-bold text-white">
                    {impactPct != null ? `+${impactPct}%` : "—"}
                  </dd>
                </div>
              </dl>
              {report.backtest_false_positive_rate != null ? (
                <p className="text-[11px] text-slate-500">
                  7-day backtest FPR: {(report.backtest_false_positive_rate * 100).toFixed(3)}%
                </p>
              ) : null}
            </>
          ) : (
            <div className="rounded-lg border border-amber-500/40 bg-amber-950/30 px-4 py-4">
              <p
                className="text-base font-semibold leading-relaxed text-amber-50"
                data-testid="promote-final-summary"
              >
                {finalSummary}
              </p>
              <p className="mt-3 text-xs text-amber-200/80">
                This action cannot be undone from this screen. Ensure stakeholders have signed off on
                the observation window.
              </p>
            </div>
          )}

          {promoteError ? (
            <p className="text-sm text-red-400" role="alert">
              {promoteError}
            </p>
          ) : null}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 px-5 py-4">
          <button
            type="button"
            onClick={handleBackdrop}
            disabled={promoteState === "loading"}
            className="rounded-lg border border-slate-600 px-3 py-2 text-sm font-medium text-slate-300 hover:bg-slate-900 disabled:opacity-50"
          >
            Cancel
          </button>
          <div className="flex gap-2">
            {step === "confirm" ? (
              <button
                type="button"
                onClick={() => setStep("review")}
                disabled={promoteState === "loading"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-2 text-sm font-medium text-slate-300 hover:bg-slate-900 disabled:opacity-50"
              >
                <ArrowLeft className="size-4" aria-hidden />
                Back
              </button>
            ) : null}
            {step === "review" ? (
              <button
                type="button"
                onClick={() => setStep("confirm")}
                className="rounded-lg border-2 border-amber-400 bg-amber-500 px-4 py-2 text-sm font-bold uppercase tracking-wide text-slate-950 hover:bg-amber-400"
                data-testid="promote-step-continue"
              >
                Continue
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void onConfirmPromote(report)}
                disabled={promoteState === "loading" || !rule}
                className="inline-flex items-center gap-2 rounded-lg border-2 border-white bg-white px-4 py-2 text-sm font-bold uppercase tracking-wide text-slate-950 hover:bg-amber-50 disabled:opacity-50"
                data-testid="promote-confirm"
              >
                {promoteState === "loading" ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <ShieldCheck className="size-4" aria-hidden />
                )}
                Promote to production
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
