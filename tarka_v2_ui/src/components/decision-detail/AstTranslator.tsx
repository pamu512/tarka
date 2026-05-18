"use client";

import { useCallback, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import type { AstTranslatorPayload } from "@/lib/ast-translator/types";

export type AstTranslatorProps = {
  /** Raw Rust/Python ``evaluation_trace`` or evidence manifest (JSON-serializable). */
  trace: unknown;
  className?: string;
};

async function postAstTranslator(trace: unknown): Promise<AstTranslatorPayload> {
  const res = await fetch("/api/v1/saarthi/ast-translator", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trace }),
  });
  const body = (await res.json().catch(() => ({}))) as AstTranslatorPayload & { error?: string };
  if (!res.ok) {
    const msg = typeof body.error === "string" ? body.error : `Ast translator failed (${res.status})`;
    throw new Error(msg);
  }
  if (typeof body.humanReason !== "string" || !Array.isArray(body.badges)) {
    throw new Error("Unexpected response shape from ast-translator");
  }
  return { humanReason: body.humanReason, badges: body.badges };
}

/**
 * Pipes a raw enforcement trace through a lightweight Saarthi/Gemini prompt and renders
 * a two-sentence **Human Reason** plus UI badge chips (Prompt 140).
 */
export function AstTranslator({ trace, className = "" }: AstTranslatorProps) {
  const [state, setState] = useState<
    "idle" | "loading" | "ok" | "error"
  >("idle");
  const [result, setResult] = useState<AstTranslatorPayload | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const run = useCallback(async () => {
    setMessage(null);
    setState("loading");
    try {
      const out = await postAstTranslator(trace);
      setResult(out);
      setState("ok");
    } catch (e) {
      setResult(null);
      setState("error");
      setMessage(e instanceof Error ? e.message : "Request failed");
    }
  }, [trace]);

  return (
    <section
      className={`rounded-lg border border-indigo-900/80 bg-indigo-950/40 ${className}`}
      aria-label="Saarthi AST translator"
    >
      <div className="flex items-center justify-between gap-2 border-b border-indigo-900/60 px-3 py-2">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-indigo-300/90">
          <Sparkles className="size-3.5 shrink-0" aria-hidden />
          Human reason (Saarthi)
        </div>
        <button
          type="button"
          onClick={() => void run()}
          disabled={state === "loading"}
          className="inline-flex items-center gap-1.5 rounded-md border border-indigo-700/80 bg-indigo-950/80 px-2.5 py-1 text-[11px] font-medium text-indigo-100 transition-colors hover:bg-indigo-900/80 disabled:opacity-60"
        >
          {state === "loading" ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : null}
          Summarize trace
        </button>
      </div>

      <div className="px-3 py-3">
        {state === "idle" ? (
          <p className="text-xs text-slate-500">
            Generate a two-sentence summary and badge tags from the raw enforcement trace via Gemini.
          </p>
        ) : null}

        {state === "loading" ? (
          <p className="flex items-center gap-2 text-xs text-indigo-200/90">
            <Loader2 className="size-4 animate-spin shrink-0" aria-hidden />
            Calling Saarthi/Gemini…
          </p>
        ) : null}

        {state === "error" && message ? (
          <p className="text-xs text-red-400">{message}</p>
        ) : null}

        {state === "ok" && result ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm leading-relaxed text-slate-100">{result.humanReason}</p>
            <ul className="flex flex-wrap gap-1.5" aria-label="Risk and policy badges">
              {result.badges.map((b) => (
                <li
                  key={b}
                  className="rounded-full border border-indigo-600/70 bg-indigo-950/90 px-2.5 py-0.5 text-[11px] font-medium text-indigo-100"
                >
                  {b}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
