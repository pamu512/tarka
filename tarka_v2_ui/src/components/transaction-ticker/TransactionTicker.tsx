"use client";

import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import {
  memo,
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  formatAmountCents,
  formatConfidence,
  ruleResultTone,
  toDisplayRow,
  type AuditRecentDisplayRow,
} from "@/lib/audit-recent-display";
import { getAuditRecentUrl } from "@/lib/audit-recent-url";
import type { AuditRecentItem, AuditRecentResponse, AuditRuleResult } from "@/types/audit-recent";

const SHADOW_GLOW_STYLE = `
@keyframes ticker-shadow-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(124, 58, 237, 0); }
  50% { box-shadow: 0 0 14px 2px rgba(124, 58, 237, 0.22); }
}
.ticker-row-shadow-review {
  animation: ticker-shadow-glow 2.4s ease-in-out infinite;
}
`;

const layoutEase = [0.22, 1, 0.36, 1] as const;
const layoutTransition = { layout: { duration: 0.2, ease: layoutEase } };

async function fetchRecent(limit: number): Promise<AuditRecentDisplayRow[]> {
  const url = getAuditRecentUrl();
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /v1/audit/recent failed (${res.status})`);
  }
  const body = (await res.json()) as AuditRecentResponse;
  return (body.items ?? []).slice(0, limit).map(toDisplayRow);
}

function stressBatch(seq: number): AuditRecentDisplayRow[] {
  return Array.from({ length: 20 }, (_, i) => {
    const k = seq * 20 + i;
    const transaction_id = `txn_stress_${seq}_${i}_${k.toString(36)}`;
    const rule_result: AuditRuleResult =
      i % 7 === 0 ? "SHADOW_REVIEW" : i % 5 === 0 ? "BLOCK" : i % 3 === 0 ? "FLAG" : "ALLOW";
    return {
      transaction_id,
      short_id: deriveStressShort(k),
      amount_cents: 10_000 + (k % 500) * 137,
      rule_result,
      ai_confidence: rule_result === "SHADOW_REVIEW" || rule_result === "FLAG" ? 0.55 + (k % 40) / 100 : null,
    };
  });
}

function deriveStressShort(k: number): string {
  return k.toString(16).padStart(8, "0").slice(-8).toUpperCase();
}

const TickerRowView = memo(function TickerRowView({
  row,
  onSelect,
}: {
  row: AuditRecentDisplayRow;
  onSelect?: (transactionId: string) => void;
}) {
  const shadow = row.rule_result === "SHADOW_REVIEW";

  return (
    <motion.div
      layout="position"
      layoutId={row.transaction_id}
      initial={false}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ ...layoutTransition, opacity: { duration: 0.12 } }}
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={() => onSelect?.(row.transaction_id)}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (!onSelect) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(row.transaction_id);
        }
      }}
      className={[
        "grid grid-cols-[5.5rem_minmax(0,1fr)_6.5rem_4.5rem] items-center gap-2 rounded-md border border-slate-800/80 bg-slate-950/50 px-3 py-2 font-mono text-xs",
        shadow && "ticker-row-shadow-review border-violet-500/20 bg-violet-950/15",
        onSelect &&
          "cursor-pointer hover:bg-slate-900/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="tabular-nums text-slate-200">{row.short_id}</span>
      <span className="text-right tabular-nums text-slate-200">
        {formatAmountCents(row.amount_cents)}
      </span>
      <span className={`truncate text-right font-medium ${ruleResultTone(row.rule_result)}`}>
        {row.rule_result}
      </span>
      <span className="text-right tabular-nums text-slate-400">
        {formatConfidence(row.ai_confidence)}
      </span>
    </motion.div>
  );
});

export type TransactionTickerProps = {
  /** Max rows from GET /v1/audit/recent. */
  limit?: number;
  pollIntervalMs?: number;
  /** Gate: 20 full list replacements in ~1s via ``startTransition``. */
  stressBurst?: boolean;
  onRowSelect?: (transactionId: string) => void;
  className?: string;
};

export function TransactionTicker({
  limit = 20,
  pollIntervalMs = 4000,
  stressBurst = false,
  onRowSelect,
  className = "",
}: TransactionTickerProps) {
  const [rows, setRows] = useState<AuditRecentDisplayRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const burstStarted = useRef(false);

  const applyRows = useCallback((next: AuditRecentDisplayRow[]) => {
    startTransition(() => {
      setErr(null);
      setRows(next);
    });
  }, []);

  useEffect(() => {
    burstStarted.current = false;
  }, [stressBurst]);

  useEffect(() => {
    if (stressBurst) return undefined;
    let cancelled = false;

    const tick = async () => {
      try {
        const next = await fetchRecent(limit);
        if (!cancelled) applyRows(next);
      } catch (e) {
        if (!cancelled) {
          startTransition(() => {
            setErr(e instanceof Error ? e.message : "Audit recent request failed");
          });
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
  }, [limit, pollIntervalMs, stressBurst, applyRows]);

  useEffect(() => {
    if (!stressBurst || burstStarted.current) return undefined;
    burstStarted.current = true;
    let seq = 0;
    const id = window.setInterval(() => {
      applyRows(stressBatch(seq));
      seq += 1;
      if (seq >= 20) window.clearInterval(id);
    }, 50);
    return () => window.clearInterval(id);
  }, [stressBurst, applyRows]);

  return (
    <>
      <style>{SHADOW_GLOW_STYLE}</style>
      <section
        aria-label="Transaction audit ticker"
        className={`flex min-h-[28rem] flex-col rounded-md border border-emerald-500/10 bg-slate-950/80 ${className}`}
      >
        <header className="flex h-11 shrink-0 items-center border-b border-emerald-500/10 px-4">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Audit-first stream
          </h2>
        </header>
        <motion.div
          layout
          className="grid grid-cols-[5.5rem_minmax(0,1fr)_6.5rem_4.5rem] items-end gap-2 border-b border-emerald-500/10 px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500"
        >
          <span>Short-ID</span>
          <span className="text-right">Amount</span>
          <span className="text-right">Rule-Result</span>
          <span className="text-right">AI-Conf.</span>
        </motion.div>
        {err ? <p className="px-3 py-2 text-xs text-red-400">{err}</p> : null}
        <LayoutGroup id="transaction-audit-ticker">
          <motion.div
            layout
            className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain divide-y divide-slate-800/60 p-2"
          >
            <AnimatePresence initial={false} mode="popLayout">
              {rows.map((row) => (
                <TickerRowView key={row.transaction_id} row={row} onSelect={onRowSelect} />
              ))}
            </AnimatePresence>
            {!err && rows.length === 0 ? (
              <p className="py-8 text-center text-xs text-slate-500">No recent audit rows</p>
            ) : null}
          </motion.div>
        </LayoutGroup>
      </section>
    </>
  );
}
