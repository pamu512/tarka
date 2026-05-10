import { useCallback, useEffect, useId, useRef, useState } from "react";

import { decisions, type AuditEntry } from "@/api/client";
import { useToast } from "@/context/ToastContext";
import { buildShadowThoughtTrace, isDeterministicAiBypass, type ThoughtTraceStep } from "@/lib/shadow-thought-trace";
import { cn } from "@/lib/utils";
import { toUserFacingError } from "@/utils/userFacingErrors";

export const DETERMINISTIC_AI_BYPASS_LABEL = "DETERMINISTIC_BLOCK: AI_BYPASSED";

export type DecisionInspectorProps = {
  tenantId: string;
  traceId: string | null;
  /** Optional subtitle (e.g. Short-ID from ticker). */
  subtitle?: string | null;
  open: boolean;
  onClose: () => void;
};

function transactionSchemaPayload(audit: AuditEntry): Record<string, unknown> {
  const ep = audit.evaluate_payload;
  if (ep && typeof ep === "object" && !Array.isArray(ep)) {
    return ep as Record<string, unknown>;
  }
  return {
    _note: "evaluate_payload absent — minimal audit projection",
    trace_id: audit.trace_id,
    tenant_id: audit.tenant_id,
    entity_id: audit.entity_id,
    event_type: audit.event_type,
    decision: audit.decision,
    score: audit.score,
    tags: audit.tags,
    rule_hits: audit.rule_hits,
  };
}

function combinedAuditJson(audit: AuditEntry): string {
  const combined: Record<string, unknown> = {
    ...audit,
    transaction_schema: transactionSchemaPayload(audit),
    shadow_thought_trace: buildShadowThoughtTrace(audit),
  };
  return JSON.stringify(combined, null, 2);
}

function ThoughtTraceList({ steps }: { steps: ThoughtTraceStep[] }) {
  return (
    <ol className="m-0 list-none space-y-0 p-0">
      {steps.map((step, i) => (
        <li key={step.id} className="relative flex gap-3 pb-7 last:pb-0">
          {i < steps.length - 1 ? (
            <span
              className="absolute left-[13px] top-8 h-[calc(100%-0.5rem)] w-px bg-violet-900/80"
              aria-hidden
            />
          ) : null}
          <div className="relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full border border-violet-600/80 bg-violet-950/90 text-[10px] font-bold text-violet-100">
            {i + 1}
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-200/95">{step.heading}</p>
              <span
                className="shrink-0 rounded border border-violet-800/80 bg-violet-950/60 px-1.5 py-0.5 font-mono text-[10px] text-violet-100/90 tabular-nums"
                title="Step confidence weight"
              >
                w={step.weight.toFixed(3)}
              </span>
            </div>
            <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-gray-300">{step.body}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function DecisionInspector({ tenantId, traceId, subtitle, open, onClose }: DecisionInspectorProps) {
  const titleId = useId();
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const { toast } = useToast();
  const [audit, setAudit] = useState<AuditEntry | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !traceId) {
      setAudit(null);
      setErr(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const row = await decisions.getAudit(traceId, tenantId, { detail_level: "analyst" });
        if (!cancelled) {
          setAudit(row);
        }
      } catch (e) {
        if (!cancelled) {
          setAudit(null);
          setErr(toUserFacingError(e, { subject: "Decision inspector", action: "load full audit" }));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, traceId, tenantId]);

  const steps = audit ? buildShadowThoughtTrace(audit) : [];
  const deterministic = audit ? isDeterministicAiBypass(audit, steps) : false;

  const handleCopyJson = useCallback(async () => {
    if (!audit) return;
    try {
      await navigator.clipboard.writeText(combinedAuditJson(audit));
      toast("Copied combined audit JSON", "success");
    } catch {
      toast("Could not copy to clipboard", "error");
    }
  }, [audit, toast]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (open) {
      closeBtnRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[200] flex justify-end" role="presentation">
      <button
        type="button"
        aria-label="Close inspector"
        className="absolute inset-0 z-0 bg-black/60 transition-opacity"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 flex h-dvh w-full max-w-[min(100vw,56rem)] flex-col border-l border-surface-700 bg-surface-950 shadow-2xl"
      >
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-surface-800 px-4">
          <div className="min-w-0">
            <h2 id={titleId} className="truncate text-sm font-semibold text-gray-100">
              Decision inspector
            </h2>
            <p className="truncate font-mono text-[11px] text-gray-500">
              {traceId}
              {subtitle ? ` · ${subtitle}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              disabled={!audit}
              onClick={() => void handleCopyJson()}
              className="rounded-md border border-surface-600 bg-surface-900 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-surface-800 disabled:opacity-40"
            >
              Copy JSON
            </button>
            <button
              ref={closeBtnRef}
              type="button"
              onClick={onClose}
              className="inline-flex size-9 items-center justify-center rounded-md border border-surface-600 text-gray-300 hover:bg-surface-900"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loading ? <p className="text-xs text-gray-500">Loading full audit…</p> : null}
          {err ? <p className="text-xs text-red-300">{err}</p> : null}
          {!loading && !err && audit ? (
            <div className="grid min-h-0 gap-6 lg:grid-cols-2">
              <section className="flex min-h-0 flex-col gap-2">
                <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">TransactionSchema</h3>
                <pre
                  className={cn(
                    "max-h-[min(70vh,520px)] overflow-auto rounded-lg border border-surface-800 bg-surface-900/80 p-3",
                    "font-mono text-[11px] leading-relaxed text-gray-200",
                  )}
                >
                  {JSON.stringify(transactionSchemaPayload(audit), null, 2)}
                </pre>
              </section>

              <section className="flex min-h-0 flex-col gap-3">
                <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">Shadow AI · Thought trace</h3>
                {deterministic ? (
                  <div
                    className="rounded-lg border border-amber-600/40 bg-amber-950/25 px-3 py-4 text-sm text-amber-100/95"
                    role="status"
                  >
                    <p className="font-mono text-xs font-semibold tracking-tight">{DETERMINISTIC_AI_BYPASS_LABEL}</p>
                    <p className="mt-2 text-xs text-amber-100/80">
                      No Shadow-AI reasoning was persisted for this transaction (for example, an early rule-engine outcome
                      may have bypassed model explainability). Rule hits and audit metadata still apply.
                    </p>
                    {audit.fallback_reason ? (
                      <p className="mt-2 font-mono text-[11px] text-amber-200/90">fallback_reason: {String(audit.fallback_reason)}</p>
                    ) : null}
                  </div>
                ) : (
                  <div className="rounded-lg border border-violet-900/40 bg-violet-950/10 p-4">
                    <ThoughtTraceList steps={steps} />
                  </div>
                )}
              </section>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
