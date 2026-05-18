/**
 * Triage “Signal Scripter” header — Sight (verdict + gauge + why) + Scan (top 3 signals) in one fold.
 * Designed to stay legible on a standard monitor without vertical scroll for this band.
 */

import type { ReactNode } from "react";
import { InfoHover } from "../InfoHover";

export type VerdictTone = "block" | "allow" | "review";

export type TriageFlashCard = {
  title: string;
  value: string;
  tone?: "critical" | "warn" | "ok" | "neutral";
  /** Raw technical disclosure — rendered on hover/focus under the scan card label. */
  hoverDetail?: ReactNode;
};

export type TriageHeaderProps = {
  /** Decision outcome from audit (e.g. allow | review | deny). */
  verdict: string;
  /** Risk / fraud score 0–100. */
  riskScore: number;
  /** Exactly three scan-layer signals (Velocity, Graph, Geo order recommended). */
  flashCards: readonly [TriageFlashCard, TriageFlashCard, TriageFlashCard];
  /** Single-line Saarthi / ML “why” — sight layer narrative. */
  saarthiLine: string | null;
  className?: string;
};

const R = 52;
const C = 2 * Math.PI * R;

function clampScore(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

function verdictVisual(decision: string): { label: string; tone: VerdictTone } {
  const d = decision.trim().toLowerCase();
  if (d === "deny") return { label: "BLOCK", tone: "block" };
  if (d === "allow") return { label: "ALLOW", tone: "allow" };
  return { label: "REVIEW", tone: "review" };
}

const verdictClasses: Record<VerdictTone, string> = {
  block: "bg-red-600 text-white border-red-400/90 shadow-[0_0_24px_rgba(239,68,68,0.35)]",
  allow: "bg-emerald-600 text-white border-emerald-400/90 shadow-[0_0_24px_rgba(16,185,129,0.3)]",
  review: "bg-amber-500 text-slate-950 border-amber-300 shadow-[0_0_20px_rgba(245,158,11,0.35)]",
};

const flashToneBorder: Record<NonNullable<TriageFlashCard["tone"]>, string> = {
  critical: "border-l-red-500 bg-red-950/50",
  warn: "border-l-amber-500 bg-amber-950/35",
  ok: "border-l-emerald-500 bg-emerald-950/30",
  neutral: "border-l-slate-500 bg-surface-800/80",
};

export function TriageHeader({
  verdict,
  riskScore,
  flashCards,
  saarthiLine,
  className = "",
}: TriageHeaderProps) {
  const score = clampScore(riskScore);
  const strokeDashoffset = C - (score / 100) * C;
  const v = verdictVisual(verdict);

  return (
    <section
      aria-label="Triage sight and scan"
      className={`rounded-xl border-2 border-surface-600 bg-surface-950/90 shadow-xl shadow-black/40 overflow-visible ${className}`}
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 lg:gap-4 p-3 sm:p-4">
        {/* Verdict + gauge — primary */}
        <div className="lg:col-span-5 flex flex-row flex-wrap items-center gap-4 min-w-0">
          <div className="flex flex-col items-start gap-2 shrink-0">
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Verdict</span>
            <span
              className={`inline-flex items-center justify-center min-w-[5.5rem] px-4 py-2 rounded-lg border-2 text-lg font-black tracking-tight ${verdictClasses[v.tone]}`}
            >
              {v.label}
            </span>
          </div>

          <div className="flex items-center gap-3 min-w-0 flex-1 justify-center sm:justify-start">
            <div className="relative w-[120px] h-[120px] shrink-0" aria-hidden>
              <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
                <defs>
                  <linearGradient id="triageGaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="rgb(16 185 129)" />
                    <stop offset="45%" stopColor="rgb(245 158 11)" />
                    <stop offset="100%" stopColor="rgb(239 68 68)" />
                  </linearGradient>
                </defs>
                <circle cx="60" cy="60" r={R} fill="none" stroke="rgb(30 41 59)" strokeWidth="10" />
                <circle
                  cx="60"
                  cy="60"
                  r={R}
                  fill="none"
                  stroke="url(#triageGaugeGrad)"
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={C}
                  strokeDashoffset={strokeDashoffset}
                  className="transition-[stroke-dashoffset] duration-500 ease-out"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none rotate-0">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Risk</span>
                <span className="text-3xl font-black tabular-nums text-white leading-none">{Math.round(score)}</span>
                <span className="text-[10px] text-gray-500 font-medium">/ 100</span>
              </div>
            </div>
            <p className="hidden sm:block text-xs text-gray-500 max-w-[10rem] leading-snug">
              Higher scores indicate stronger automated fraud signals on this trace.
            </p>
          </div>
        </div>

        {/* Flash cards — secondary */}
        <div className="lg:col-span-7 grid grid-cols-3 gap-2 min-h-0 min-w-0">
          {flashCards.map((card) => {
            const tone = card.tone ?? "neutral";
            const b = flashToneBorder[tone];
            return (
              <div
                key={card.title}
                className={`rounded-lg border border-surface-700 border-l-4 px-2.5 py-2 flex flex-col justify-center gap-0.5 min-w-0 ${b}`}
              >
                <span className="text-[10px] font-bold uppercase tracking-wide text-gray-500 truncate">{card.title}</span>
                <span className="text-sm font-semibold text-gray-100 truncate min-w-0">
                  {card.hoverDetail ? (
                    <InfoHover heading={card.title} detail={card.hoverDetail}>
                      {card.value}
                    </InfoHover>
                  ) : (
                    <span title={`${card.title}: ${card.value}`}>{card.value}</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Saarthi one-liner — tertiary */}
      <div className="border-t border-surface-700 bg-black/25 px-3 sm:px-4 py-2">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-brand-400/90 mb-1">Why (sight)</p>
        <p className="text-sm text-gray-200 leading-snug line-clamp-1">
          {saarthiLine?.trim() ? (
            saarthiLine.trim()
          ) : (
            <span className="text-gray-500 italic">No narrative attached — open Scan tabs for evidence.</span>
          )}
        </p>
      </div>
    </section>
  );
}
