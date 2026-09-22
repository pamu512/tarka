import { useState } from "react";

import { backtestJobs, type RulePack } from "@/api/client";

const MS_PER_DAY = 86_400_000;

/** Strip UI-only keys (mirrors BacktestJobConfigurator.rulePackForApi). */
function rulePackForApi(raw: RulePack): Record<string, unknown> {
  const out: Record<string, unknown> = { ...(raw as unknown as Record<string, unknown>) };
  delete out._file;
  for (const k of Object.keys(out)) {
    if (k.startsWith("__")) delete out[k];
  }
  return out;
}

export function DraftBacktestButton({
  pack,
  tenantId,
  windowDays = 7,
}: {
  pack: RulePack;
  tenantId: string;
  windowDays?: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    setError(null);
    setJobId(null);
    const end = new Date();
    const start = new Date(end.getTime() - windowDays * MS_PER_DAY);
    try {
      const resp = await backtestJobs.enqueue({
        tenant_id: tenantId,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        rule_pack: rulePackForApi(pack),
        clickhouse_max_execution_seconds: 60,
      });
      setJobId(resp.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={onClick}
        disabled={busy || !pack?.rules?.length}
        className="px-3 py-1.5 bg-surface-700 hover:bg-surface-600 disabled:opacity-40 disabled:cursor-not-allowed text-gray-200 text-sm rounded-lg transition-colors"
        title={`Enqueue a warehouse backtest of this draft over the last ${windowDays} days`}
      >
        {busy ? "Backtesting…" : `Backtest draft (${windowDays}d)`}
      </button>
      {jobId && (
        <a
          href={`/ops/backtest?job_id=${encodeURIComponent(jobId)}`}
          className="text-brand-400 hover:text-brand-300 text-xs font-mono"
        >
          job {jobId.slice(0, 8)}
        </a>
      )}
      {error && <span className="text-xs text-red-400 max-w-[24rem] truncate" title={error}>{error}</span>}
    </div>
  );
}
