"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

export type DecisionSummaryProps = {
  /** Backend execution trace (JSON-serializable) shipped with the decision payload. */
  execution_trace: unknown;
  className?: string;
  /** When true, request Saarthi once on mount / when trace identity changes. */
  autoGenerate?: boolean;
};

export type DecisionSummaryResponse = {
  summary: string;
};

async function postDecisionSummary(execution_trace: unknown): Promise<DecisionSummaryResponse> {
  const res = await fetch("/api/v1/saarthi/decision-summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ execution_trace }),
  });
  const body = (await res.json().catch(() => ({}))) as DecisionSummaryResponse & { error?: string; detail?: string };
  if (!res.ok) {
    const msg =
      typeof body.error === "string"
        ? body.detail
          ? `${body.error}: ${body.detail}`
          : body.error
        : `Decision summary failed (${res.status})`;
    throw new Error(msg);
  }
  if (typeof body.summary !== "string" || !body.summary.trim()) {
    throw new Error("Unexpected response shape from decision-summary");
  }
  return { summary: body.summary.trim() };
}

/**
 * Saarthi reasoning injection (Gemini 1.5 Pro): turns a technical **execution_trace** into a single
 * analyst-facing sentence — never surfaces raw graph scores as the primary readout.
 */
export function DecisionSummary({ execution_trace, className = "", autoGenerate = false }: DecisionSummaryProps) {
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [summary, setSummary] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const traceKey = useMemo(() => {
    try {
      return JSON.stringify(execution_trace);
    } catch {
      return String(execution_trace);
    }
  }, [execution_trace]);

  const run = useCallback(async () => {
    setMessage(null);
    setState("loading");
    try {
      const out = await postDecisionSummary(execution_trace);
      setSummary(out.summary);
      setState("ok");
    } catch (e) {
      setSummary(null);
      setState("error");
      setMessage(e instanceof Error ? e.message : "Request failed");
    }
  }, [execution_trace]);

  useEffect(() => {
    if (!autoGenerate) return;
    void run();
  }, [autoGenerate, run, traceKey]);

  return (
    <section
      className={`rounded-lg border border-emerald-900/80 bg-emerald-950/35 ${className}`}
      aria-label="Saarthi decision summary"
    >
      <div className="flex items-center justify-between gap-2 border-b border-emerald-900/55 px-3 py-2">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-emerald-300/90">
          <Sparkles className="size-3.5 shrink-0" aria-hidden />
          Checkout narrative (Saarthi)
        </div>
        {!autoGenerate ? (
          <button
            type="button"
            onClick={() => void run()}
            disabled={state === "loading"}
            className="inline-flex items-center gap-1.5 rounded-md border border-emerald-700/80 bg-emerald-950/80 px-2.5 py-1 text-[11px] font-medium text-emerald-100 transition-colors hover:bg-emerald-900/80 disabled:opacity-60"
          >
            {state === "loading" ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : null}
            Generate sentence
          </button>
        ) : null}
      </div>

      <div className="px-3 py-3 space-y-2">
        {state === "idle" && !autoGenerate ? (
          <p className="text-xs text-slate-500">
            Translate the execution trace into one human-readable risk sentence (blocked at checkout).
          </p>
        ) : null}

        {state === "loading" ? (
          <p className="flex items-center gap-2 text-xs text-emerald-200/90">
            <Loader2 className="size-4 animate-spin shrink-0" aria-hidden />
            Calling Saarthi (Gemini 1.5 Pro)…
          </p>
        ) : null}

        {state === "error" && message ? (
          <p className="text-xs text-red-400">{message}</p>
        ) : null}

        {state === "ok" && summary ? (
          <p className="text-sm leading-relaxed text-slate-100" data-testid="saarthi-decision-summary">
            {summary}
          </p>
        ) : null}

        {/* Intentionally no raw execution_trace / graph scores in the primary analyst surface (Prompt 144 gate). */}
      </div>
    </section>
  );
}
