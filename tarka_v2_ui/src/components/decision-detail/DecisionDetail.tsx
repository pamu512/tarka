"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import useSWR from "swr";
import { X } from "lucide-react";
import { JsonCodeBlock } from "@/components/decision-detail/JsonCodeBlock";
import { CoTTimeline } from "@/components/decision-detail/CoTTimeline";
import { TimelineView } from "@/components/decision-detail/TimelineView";
import { parseAiReasoning } from "@/lib/parse-ai-reasoning";
import type { DecisionDetailResponse } from "@/types/decision-detail";
import {
  KnowledgeDropInsight,
  type KnowledgeResolution,
} from "@/components/decision-detail/KnowledgeDropInsight";
import { AstTranslator } from "@/components/decision-detail/AstTranslator";

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

const SHADOW_LENS_OPTIONS = [
  { value: "policy", label: "Policy lens" },
  { value: "evidence", label: "Evidence graph" },
  { value: "velocity", label: "Velocity & linkage" },
] as const;

type PrimeResponse = {
  filename?: string;
  detected_ids?: string[];
  prime_prompt?: string;
  knowledge?: KnowledgeResolution[];
  cluster_analysis?: { ai_reasoning?: string } | null;
};

function normalizeKnowledge(raw: unknown): KnowledgeResolution[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const out: KnowledgeResolution[] = [];
  for (const x of raw) {
    if (!x || typeof x !== "object") continue;
    const o = x as Record<string, unknown>;
    if (typeof o.detected_id !== "string") continue;
    out.push({
      detected_id: o.detected_id,
      id_kind: typeof o.id_kind === "string" ? o.id_kind : "unknown",
      found_in_graph: Boolean(o.found_in_graph),
      match_kind: typeof o.match_kind === "string" ? o.match_kind : null,
      graph_backend: typeof o.graph_backend === "string" ? o.graph_backend : null,
      linked_user_ids: Array.isArray(o.linked_user_ids)
        ? o.linked_user_ids.filter((u): u is string => typeof u === "string")
        : [],
      active_investigation_count:
        typeof o.active_investigation_count === "number" ? o.active_investigation_count : 0,
      pending_action_conflict: Boolean(o.pending_action_conflict),
      pending_action_case_ids: Array.isArray(o.pending_action_case_ids)
        ? o.pending_action_case_ids.filter((c): c is string => typeof c === "string")
        : [],
      mini_graph:
        o.mini_graph && typeof o.mini_graph === "object"
          ? (o.mini_graph as KnowledgeResolution["mini_graph"])
          : undefined,
      two_hop_network:
        o.two_hop_network && typeof o.two_hop_network === "object"
          ? (o.two_hop_network as KnowledgeResolution["two_hop_network"])
          : undefined,
      duck_cluster_velocity:
        o.duck_cluster_velocity && typeof o.duck_cluster_velocity === "object"
          ? (o.duck_cluster_velocity as KnowledgeResolution["duck_cluster_velocity"])
          : undefined,
    });
  }
  return out;
}

function isAllowedPrimeFile(file: File): boolean {
  const n = file.name.toLowerCase();
  return n.endsWith(".pdf") || n.endsWith(".txt");
}

export function DecisionDetail({ transactionId, onClose }: DecisionDetailProps) {
  const titleId = useId();
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const primeFileInputRef = useRef<HTMLInputElement>(null);
  const closingRef = useRef(false);

  const [animateIn, setAnimateIn] = useState(false);
  const [shadowLens, setShadowLens] = useState<string>(SHADOW_LENS_OPTIONS[0].value);
  const [shadowChat, setShadowChat] = useState("");
  const [primeBusy, setPrimeBusy] = useState(false);
  const [primeError, setPrimeError] = useState<string | null>(null);
  const [primeKnowledge, setPrimeKnowledge] = useState<KnowledgeResolution[] | null>(null);
  const [primeClusterAnalysis, setPrimeClusterAnalysis] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);

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

  const runPrimeUpload = useCallback(async (file: File) => {
    setPrimeError(null);
    setPrimeKnowledge(null);
    setPrimeClusterAnalysis(null);
    if (!isAllowedPrimeFile(file)) {
      setPrimeError("Only .pdf and .txt files are supported.");
      return;
    }
    setPrimeBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/v1/investigation/prime", { method: "POST", body: fd });
      const body = (await res.json().catch(() => ({}))) as PrimeResponse & { error?: string };
      if (!res.ok) {
        const msg =
          typeof body.error === "string"
            ? body.error
            : `Prime failed (${res.status})`;
        setPrimeError(msg);
        return;
      }
      setPrimeKnowledge(normalizeKnowledge(body.knowledge));
      const ca = body.cluster_analysis;
      const clusterText =
        ca && typeof ca === "object" && typeof ca.ai_reasoning === "string" ? ca.ai_reasoning.trim() : "";
      setPrimeClusterAnalysis(clusterText.length > 0 ? clusterText : null);
      const prompt = typeof body.prime_prompt === "string" ? body.prime_prompt.trim() : "";
      if (prompt.length > 0) {
        setShadowChat(prompt);
      } else {
        setPrimeError("No reference IDs (order, transaction, customer, etc.) were detected in that document.");
      }
    } catch {
      setPrimeError("Network error while priming.");
    } finally {
      setPrimeBusy(false);
    }
  }, []);

  const onDropFiles = useCallback(
    (fl: FileList | File[] | null) => {
      if (!fl || fl.length === 0) return;
      const file = fl[0];
      void runPrimeUpload(file);
    },
    [runPrimeUpload],
  );

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
            <div className="flex min-h-0 flex-col gap-6">
              <TimelineView transactionId={transactionId} />
              {data.evaluation_trace != null ? (
                <AstTranslator trace={data.evaluation_trace} />
              ) : null}
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

                <div className="flex flex-col gap-3 rounded-md border border-slate-800/90 bg-slate-900/20 p-4">
                  <div className="flex flex-col gap-1.5">
                    <label
                      htmlFor={`${titleId}-shadow-lens`}
                      className="text-[10px] font-semibold uppercase tracking-widest text-slate-500"
                    >
                      Shadow lens
                    </label>
                    <select
                      id={`${titleId}-shadow-lens`}
                      value={shadowLens}
                      onChange={(e) => setShadowLens(e.target.value)}
                      className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-slate-500"
                    >
                      {SHADOW_LENS_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                      Knowledge drop zone
                    </span>
                    <div
                      role="button"
                      tabIndex={0}
                      aria-busy={primeBusy}
                      onClick={() => primeFileInputRef.current?.click()}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          primeFileInputRef.current?.click();
                        }
                      }}
                      onDragEnter={(e) => {
                        e.preventDefault();
                        setDropActive(true);
                      }}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDropActive(true);
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                          setDropActive(false);
                        }
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        setDropActive(false);
                        onDropFiles(e.dataTransfer.files);
                      }}
                      className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-4 py-8 text-center transition-colors ${
                        dropActive
                          ? "border-sky-500/80 bg-sky-950/30 text-sky-100"
                          : "border-slate-700 bg-slate-950/40 text-slate-400 hover:border-slate-600 hover:text-slate-300"
                      }`}
                    >
                      <input
                        ref={primeFileInputRef}
                        type="file"
                        accept=".pdf,.txt,application/pdf,text/plain"
                        className="sr-only"
                        aria-label="Upload knowledge document"
                        disabled={primeBusy}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          e.target.value = "";
                          if (f) void runPrimeUpload(f);
                        }}
                      />
                      <span className="text-xs font-medium text-slate-200">
                        Drop a .pdf or .txt here
                      </span>
                      <span className="text-[11px] text-slate-500">
                        IDs are parsed locally via the orchestrator; the Shadow prompt updates below.
                      </span>
                    </div>
                    {primeBusy ? (
                      <p className="text-[11px] text-slate-500">Parsing document…</p>
                    ) : null}
                    {primeError ? (
                      <p className="text-[11px] text-amber-400/90">{primeError}</p>
                    ) : null}
                    {primeKnowledge && primeKnowledge.length > 0 ? (
                      <KnowledgeDropInsight rows={primeKnowledge} />
                    ) : null}
                    {primeClusterAnalysis ? (
                      <div className="rounded-md border border-slate-700 bg-slate-950/60 px-3 py-2">
                        <p className="text-[10px] font-semibold uppercase tracking-widest text-sky-400/90">
                          Shadow — Cluster Analysis
                        </p>
                        <p className="mt-1 whitespace-pre-wrap font-sans text-[11px] leading-relaxed text-slate-200">
                          {primeClusterAnalysis}
                        </p>
                      </div>
                    ) : null}
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <label
                      htmlFor={`${titleId}-shadow-chat`}
                      className="text-[10px] font-semibold uppercase tracking-widest text-slate-500"
                    >
                      Shadow AI
                    </label>
                    <textarea
                      id={`${titleId}-shadow-chat`}
                      value={shadowChat}
                      onChange={(e) => setShadowChat(e.target.value)}
                      rows={5}
                      placeholder="Ask Shadow to reason about this decision, or drop a document above to prime from extracted IDs…"
                      className="resize-y rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-sans text-xs leading-relaxed text-slate-100 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none"
                    />
                  </div>
                </div>
              </section>
            </div>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
