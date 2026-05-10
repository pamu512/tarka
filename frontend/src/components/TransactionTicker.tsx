import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { memo, startTransition, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { decisions, type AuditRecentItem, type AuditRuleResult } from "@/api/client";
import { cn } from "@/lib/utils";
import { toUserFacingError } from "@/utils/userFacingErrors";

const SHADOW_GLOW_STYLE = `
@keyframes ticker-audit-shadow-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(124, 58, 237, 0); }
  50% { box-shadow: 0 0 16px 2px rgba(124, 58, 237, 0.26); }
}
.ticker-audit-shadow-review {
  animation: ticker-audit-shadow-glow 2.5s ease-in-out infinite;
}
`;

const layoutEase = [0.22, 1, 0.36, 1] as const;
const layoutTransition = { layout: { duration: 0.2, ease: layoutEase } };

function formatAmount(amount: number | null, currency: string | null): string {
  if (amount == null) return "—";
  const c = currency?.trim();
  if (c && /^[A-Za-z]{3}$/.test(c)) {
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: c.toUpperCase(),
        maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      /* invalid ISO currency */
    }
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(amount);
}

function formatConfidence(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%`;
}

function resultTone(rr: AuditRuleResult): string {
  switch (rr) {
    case "ALLOW":
      return "text-emerald-400";
    case "DENY":
      return "text-red-400";
    case "SHADOW_REVIEW":
      return "text-violet-300";
    default:
      return "text-amber-300";
  }
}

/** Deterministic 20-row batch for stressBurst (gate: 20 updates in 1s). */
function stressBatch(seq: number): AuditRecentItem[] {
  return Array.from({ length: 20 }, (_, i) => {
    const k = seq * 20 + i;
    const trace_id = `00000000-0000-4000-8000-${(0x900000000000 + k).toString(16).padStart(12, "0").slice(-12)}`;
    const short = trace_id.replace(/-/g, "").slice(0, 8).toUpperCase();
    const rule_result: AuditRuleResult =
      i % 7 === 0 ? "SHADOW_REVIEW" : i % 5 === 0 ? "DENY" : i % 3 === 0 ? "REVIEW" : "ALLOW";
    return {
      trace_id,
      short_id: short,
      amount: Math.round((k % 5000) * 100) / 100,
      currency: "USD",
      rule_result,
      ai_confidence: Math.min(0.99, 0.4 + ((k * 13) % 55) / 100),
      created_at: new Date().toISOString(),
    };
  });
}

const TickerRowView = memo(function TickerRowView({
  item,
  onSelect,
}: {
  item: AuditRecentItem;
  onSelect?: (row: AuditRecentItem) => void;
}) {
  const shadow = item.rule_result === "SHADOW_REVIEW";
  return (
    <motion.div
      layout="position"
      layoutId={item.trace_id}
      initial={false}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ ...layoutTransition, opacity: { duration: 0.12 } }}
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={() => onSelect?.(item)}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (!onSelect) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(item);
        }
      }}
      className={cn(
        "grid grid-cols-[5.5rem_minmax(0,1fr)_6.5rem_4.5rem] gap-2 items-center px-3 py-2 rounded-md border border-surface-800/80 bg-surface-900/40 text-xs",
        shadow && "ticker-audit-shadow-review border-violet-500/25",
        onSelect && "cursor-pointer hover:bg-surface-800/35 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/55",
      )}
    >
      <span className="font-mono text-gray-200 tabular-nums">{item.short_id}</span>
      <span className="text-right text-gray-200 tabular-nums">{formatAmount(item.amount, item.currency)}</span>
      <span className={cn("font-medium text-right truncate", resultTone(item.rule_result))}>{item.rule_result}</span>
      <span className="text-right text-gray-400 tabular-nums">{formatConfidence(item.ai_confidence)}</span>
    </motion.div>
  );
});

export interface TransactionTickerProps {
  tenantId: string;
  /** Polling interval when ``stressBurst`` is false. */
  pollIntervalMs?: number;
  limit?: number;
  /** When true, applies 20 list replacements over ~1s (non-blocking ``startTransition``) for gate testing. */
  stressBurst?: boolean;
  /** Opens decision inspector / drill-down when a row is activated. */
  onRowSelect?: (row: AuditRecentItem) => void;
  className?: string;
}

export function TransactionTicker({
  tenantId,
  pollIntervalMs = 4000,
  limit = 50,
  stressBurst = false,
  onRowSelect,
  className,
}: TransactionTickerProps) {
  const [items, setItems] = useState<AuditRecentItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const burstStarted = useRef(false);

  useEffect(() => {
    burstStarted.current = false;
  }, [tenantId]);

  useEffect(() => {
    if (stressBurst) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await decisions.recentAudit(tenantId, limit);
        if (cancelled) return;
        startTransition(() => {
          setErr(null);
          setItems(res.items ?? []);
        });
      } catch (e) {
        if (!cancelled) {
          startTransition(() => setErr(toUserFacingError(e, { subject: "Audit ticker", action: "load recent audits" })));
        }
      }
    };
    void tick();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void tick();
    }, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [tenantId, pollIntervalMs, limit, stressBurst]);

  useEffect(() => {
    if (!stressBurst || burstStarted.current) return undefined;
    burstStarted.current = true;
    let seq = 0;
    const id = window.setInterval(() => {
      const batch = stressBatch(seq);
      seq += 1;
      startTransition(() => {
        setErr(null);
        setItems(batch);
      });
      if (seq >= 20) window.clearInterval(id);
    }, 50);
    return () => window.clearInterval(id);
  }, [stressBurst]);

  return (
    <>
      <style>{SHADOW_GLOW_STYLE}</style>
      <div className={cn("rounded-lg border border-surface-700 bg-surface-950/30", className)}>
        <div className="grid grid-cols-[5.5rem_minmax(0,1fr)_6.5rem_4.5rem] gap-2 items-end px-3 py-2 border-b border-surface-800 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
          <span>Short-ID</span>
          <span className="text-right">Amount</span>
          <span className="text-right">Rule-Result</span>
          <span className="text-right">AI-Conf.</span>
        </div>
        {err ? <p className="px-3 py-2 text-xs text-red-300/90">{err}</p> : null}
        <LayoutGroup id={`audit-ticker-${tenantId}`}>
          <div className="max-h-[min(420px,55vh)] overflow-y-auto overscroll-y-contain divide-y divide-surface-800/90">
            <AnimatePresence initial={false} mode="popLayout">
              {items.map((item) => (
                <TickerRowView key={item.trace_id} item={item} onSelect={onRowSelect} />
              ))}
            </AnimatePresence>
            {!err && items.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-gray-500">No recent audit rows</p>
            ) : null}
          </div>
        </LayoutGroup>
      </div>
    </>
  );
}
