import { useCallback, useEffect, useState } from "react";

import { decisions } from "@/api/client";

type Report = Awaited<ReturnType<typeof decisions.arenaReport>>;
type Config = Awaited<ReturnType<typeof decisions.arenaConfig>>;

/** Challenger bake-off arena (P2): weekly champion report with honest nulls.
 * Champions/challengers are pack metrics — no third-party desk names. */
export function ArenaPanel({ tenantId }: { tenantId: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchIt = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, c] = await Promise.all([
        decisions.arenaReport(tenantId),
        decisions.arenaConfig(tenantId).catch(() => null),
      ]);
      setReport(r);
      setConfig(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchIt();
  }, [fetchIt]);

  const cell = (v: number | null | undefined, fmt: (n: number) => string) =>
    v == null ? <span className="text-gray-600">— unknown</span> : <span className="font-mono">{fmt(v)}</span>;

  const challengers = Object.entries(report?.challengers ?? {});
  const names = config?.challengers ? Object.keys(config.challengers) : [];

  return (
    <section className="rounded-xl border border-surface-700 bg-surface-800 p-4" data-testid="arena-panel">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-200">Challenger arena (shadow)</h3>
          <p className="text-xs text-gray-500">
            {config?.configured
              ? `${names.length} challenger${names.length === 1 ? "" : "s"} wired · weekly champion report`
              : "no challengers wired (admin PUT /v1/ops/arena/config)"}
          </p>
        </div>
        <button
          onClick={() => void fetchIt()}
          disabled={loading}
          className="px-2 py-1 text-xs rounded-lg bg-surface-700 hover:bg-surface-600 disabled:opacity-40 text-gray-300"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </header>

      {error && <p className="text-xs text-red-400" role="alert">{error}</p>}

      {report && report.n === 0 && (
        <p className="text-xs text-gray-500">
          No shadow records yet — the ledger fills as evaluate traffic runs with a challenger wired.
        </p>
      )}

      {challengers.length > 0 && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-500 border-b border-surface-700">
              <th className="py-1 pr-2 font-medium">Challenger</th>
              <th className="py-1 pr-2 font-medium">n</th>
              <th className="py-1 pr-2 font-medium">Divergence</th>
              <th className="py-1 font-medium">FP delta</th>
            </tr>
          </thead>
          <tbody>
            {challengers.map(([name, m]) => (
              <tr key={name} className="border-b border-surface-700/50">
                <td className="py-1 pr-2 text-gray-300">{name}</td>
                <td className="py-1 pr-2">{cell(m.n, (n) => String(n))}</td>
                <td className="py-1 pr-2">{cell(m.divergence_rate, (n) => `${(n * 100).toFixed(1)}%`)}</td>
                <td className="py-1">{cell(m.fp_delta, (n) => (n > 0 ? "+" : "") + (n * 100).toFixed(1) + "pp")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {report && report.n > 0 && (
        <p className="mt-2 text-[11px] text-gray-600">
          n = shadow records in ledger window ({report.n}). FP delta null = labels unknown — never zero.
          Challengers never decide, never Promote.
        </p>
      )}
    </section>
  );
}
