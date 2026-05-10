"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import useSWR from "swr";
import { X } from "lucide-react";
import { JsonCodeBlock } from "@/components/decision-detail/JsonCodeBlock";
import { CoTTimeline } from "@/components/decision-detail/CoTTimeline";
import { parseAiReasoning } from "@/lib/parse-ai-reasoning";
import type { DecisionDetailResponse } from "@/types/decision-detail";

export type DecisionDetailProps = {
  transactionId: string;
  onClose: () => void;
};

function decisionDetailUrl(transactionId: string): string {
  const base =
    typeof process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL === "string"
      ? process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL.replace(/\/$/, "")
      : "";
  if (base.length > 0) {
    return `${base}/v1/decisions/${encodeURIComponent(transactionId)}`;
  }
  return `/api/v1/decisions/${encodeURIComponent(transactionId)}`;
}

const fetcher = async (url: string): Promise<DecisionDetailResponse> => {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Decision detail failed (${res.status})`);
  }
  return res.json() as Promise<DecisionDetailResponse>;
};

export function DecisionDetail({ transactionId, onClose }: DecisionDetailProps) {
  const titleId = useId();
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const closingRef = useRef(false);

  const [animateIn, setAnimateIn] = useState(false);

  useEffect(() => {
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        setAnimateIn(true);
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      if (inner) cancelAnimationFrame(inner);
    };
  }, []);

  const url = decisionDetailUrl(transactionId);
  const { data, error, isLoading } = useSWR(url, fetcher);

  const cotSteps = data ? parseAiReasoning(data.shadow_decision.ai_reasoning) : [];

  const requestClose = useCallback(() => {
    closingRef.current = true;
    setAnimateIn(false);
  }, []);

  useEffect(() => {
    if (!animateIn) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [animateIn, requestClose]);

  useEffect(() => {
    if (!animateIn) return;
    closeBtnRef.current?.focus();
  }, [animateIn]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  const onPanelTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.propertyName !== "transform") return;
      if (closingRef.current && !animateIn) {
        closingRef.current = false;
        onClose();
      }
    },
    [animateIn, onClose],
  );

  const panelVisible = animateIn;
  const backdropClass = panelVisible ? "opacity-100" : "opacity-0";
  const panelClass = panelVisible ? "translate-x-0" : "translate-x-full";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
      <button
        type="button"
        aria-label="Close decision detail"
        className={`absolute inset-0 z-0 bg-black/65 transition-opacity duration-300 ease-out ${backdropClass}`}
        onClick={requestClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onTransitionEnd={onPanelTransitionEnd}
        className={`relative z-10 flex h-dvh w-full max-w-[min(100vw,56rem)] flex-col border-l border-slate-800 bg-slate-950 shadow-2xl transition-transform duration-300 ease-out ${panelClass}`}
      >
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-slate-800 px-4">
          <h2 id={titleId} className="min-w-0 truncate text-sm font-semibold text-slate-100">
            Decision detail
            <span className="mt-0.5 block truncate font-mono text-xs font-normal text-slate-500">
              {transactionId}
            </span>
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={requestClose}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-slate-700 text-slate-300 transition-colors hover:bg-slate-900 hover:text-slate-100"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {error ? (
            <p className="text-xs text-red-400">{error.message}</p>
          ) : isLoading && !data ? (
            <p className="text-xs text-slate-500">Loading decision payload…</p>
          ) : data ? (
            <div className="grid min-h-0 gap-6 lg:grid-cols-2">
              <section className="flex min-h-0 flex-col gap-2">
                <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                  TransactionSchema
                </h3>
                <JsonCodeBlock
                  value={data.transaction_schema}
                  aria-label="Raw transaction schema JSON"
                />
              </section>

              <section className="flex min-h-0 flex-col gap-4">
                <div className="flex min-h-0 flex-col gap-2">
                  <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                    ShadowDecision
                  </h3>
                  <JsonCodeBlock
                    value={data.shadow_decision}
                    aria-label="Shadow decision JSON"
                  />
                </div>
                <div className="rounded-md border border-slate-800/90 bg-slate-900/30 p-4">
                  <CoTTimeline steps={cotSteps} />
                </div>
              </section>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
