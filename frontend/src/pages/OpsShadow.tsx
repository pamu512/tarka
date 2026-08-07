import { useEffect, useState } from "react";
import { decisions } from "../api/v1/decisions";

type ShadowPromoteGate = {
  schema_id: string;
  vertical?: string;
  blocked?: { promote_allowed?: boolean; blockers?: string[] };
  allowed?: { promote_allowed?: boolean };
  recipe_path?: string;
  smoke?: string;
};

const L3_WEEK_ROWS = [1, 2, 3, 4] as const;

export default function OpsShadow() {
  const [data, setData] = useState<ShadowPromoteGate | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    void decisions
      .shadowPromoteGate()
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-gray-100">Shadow vs primary</h1>
      <p className="text-sm text-gray-400">
        Promote-gate posture for shadow experiments. Warehouse diffs use the SQL recipe.
      </p>

      <section
        className="rounded-xl border border-amber-500/35 bg-amber-950/20 px-4 py-3 space-y-3"
        data-testid="l3-ops-ledger-panel"
        aria-label="L3 ops ledger status"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-amber-100">L3 ops ledger (four-week live shadow)</h2>
          <span className="text-[10px] font-bold uppercase tracking-wide rounded-full border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-amber-200">
            NOT STARTED
          </span>
        </div>
        <p className="text-xs text-amber-100/85 leading-relaxed">
          Starting this panel does <strong className="font-semibold">not</strong> start L3. L3 requires a named live
          tenant, host action log sink, and Week 1 checklist — not{" "}
          <code className="font-mono text-amber-200/90">shadow_four_week_sim.py</code> (
          <span className="font-mono">NOT PRODUCTION L3</span>).
        </p>
        <dl className="grid gap-1 text-[11px] text-gray-300 sm:grid-cols-2 font-mono">
          <div>
            Tenant id: <span className="text-gray-500">pending operator</span>
          </div>
          <div>
            Week 1 start (UTC): <span className="text-gray-500">not set</span>
          </div>
          <div>
            Shadow evaluate: <span className="text-gray-500">no</span>
          </div>
          <div>
            Host action sink: <span className="text-gray-500">no</span>
          </div>
          <div>
            Label join / ECE (real labels): <span className="text-gray-500">no</span>
          </div>
        </dl>
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] text-left text-gray-400">
            <thead>
              <tr className="border-b border-amber-500/25 text-amber-200/80">
                <th className="py-1 pr-2 font-semibold">Week</th>
                <th className="py-1 pr-2">Shadow</th>
                <th className="py-1 pr-2">Host actions</th>
                <th className="py-1 pr-2">Outcomes</th>
                <th className="py-1 pr-2">Metrics</th>
                <th className="py-1">Sign-off</th>
              </tr>
            </thead>
            <tbody>
              {L3_WEEK_ROWS.map((w) => (
                <tr key={w} className="border-b border-surface-800/80">
                  <td className="py-1 pr-2 font-mono text-gray-300">{w}</td>
                  <td className="py-1 pr-2">☐</td>
                  <td className="py-1 pr-2">☐</td>
                  <td className="py-1 pr-2">☐</td>
                  <td className="py-1 pr-2">☐</td>
                  <td className="py-1">☐</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-gray-500">
          Operator playbook:{" "}
          <span className="font-mono text-gray-400">docs/superpowers/playbooks/l3-ops-ledger.md</span>
        </p>
      </section>

      {err ? <p className="text-red-400">{err}</p> : null}
      {data ? (
        <>
          <div>
            Underpowered metrics: promote{" "}
            {data.blocked?.promote_allowed ? "allowed" : "blocked"}
          </div>
          <div>
            Healthy metrics: promote {data.allowed?.promote_allowed ? "allowed" : "blocked"}
          </div>
          <code className="text-xs">{data.recipe_path}</code>
        </>
      ) : null}
    </div>
  );
}
