"use client";

import type { ChainOfThoughtStep } from "@/lib/parse-ai-reasoning";

type CoTTimelineProps = {
  steps: ChainOfThoughtStep[];
};

export function CoTTimeline({ steps }: CoTTimelineProps) {
  if (steps.length === 0) {
    return (
      <p className="text-xs text-slate-500">
        No <code className="text-slate-400">ai_reasoning</code> steps returned for
        this decision.
      </p>
    );
  }

  return (
    <div>
      <h3 className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
        Chain of thought
      </h3>
      <ol className="m-0 list-none space-y-0 p-0">
        {steps.map((step, i) => (
          <li key={`${step.stepIndex}-${i}`} className="relative flex gap-4 pb-8 last:pb-0">
            {i < steps.length - 1 ? (
              <span
                className="absolute left-[13px] top-8 h-[calc(100%-0.5rem)] w-px bg-slate-700"
                aria-hidden
              />
            ) : null}
            <div className="relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full border border-purple-600/70 bg-purple-950 text-[10px] font-bold text-purple-200">
              {i + 1}
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-purple-200/95">
                {step.heading}
              </p>
              <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">
                {step.body}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
