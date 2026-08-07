import { useEffect, useState } from "react";
import { decisions } from "../api/v1/decisions";

type ShadowPromoteGate = {
  schema_id: string;
  vertical?: string;
  blocked?: { promote_allowed?: boolean; blockers?: string[] };
  allowed?: { promote_allowed?: boolean };
  label_gated_promote?: {
    promote_allowed?: boolean;
    blockers?: string[];
    label_posture?: Record<string, unknown>;
  };
  mcnemar_promote_gate?: {
    promote_allowed?: boolean;
    blockers?: string[];
    discordant_pairs?: number;
    min_discordant_pairs?: number;
  };
  drift_promote_gate?: {
    promote_allowed?: boolean;
    blockers?: string[];
    drift_score?: number | null;
    hint?: string | null;
  };
  desk_promote_gate?: {
    promote_allowed?: boolean;
    blockers?: string[];
    requires?: string[];
  };
  champion_challenger?: {
    rows_with_policy_routing?: number;
    decision_agreement_rate?: number | null;
    decisions_agree_count?: number;
    audit_rows?: Array<{
      trace_id?: string | null;
      champion_decision?: string;
      challenger_decision?: string;
      decisions_agree?: boolean;
    }>;
  };
  recipe_path?: string;
  smoke?: string;
  honesty?: string;
};

type TypologyTelemetry = {
  typology_count?: number;
  configured?: Array<{
    id: string;
    label?: string;
    weight_per_rule_hit?: number;
    breach_thresholds?: { warning?: number; alert?: number };
  }>;
  aggregation?: { mode?: string; note?: string };
};

const L3_WEEK_ROWS = [1, 2, 3, 4] as const;

export default function OpsShadow() {
  const [tenantId, setTenantId] = useState("demo");
  const [data, setData] = useState<ShadowPromoteGate | null>(null);
  const [typology, setTypology] = useState<TypologyTelemetry | null>(null);
  const [backtestPosture, setBacktestPosture] = useState<{
    require_backtest_before_promote?: boolean;
    note?: string;
    ui?: string;
  } | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    void decisions
      .shadowPromoteGate(tenantId)
      .then(setData)
      .catch((e) => setErr(String(e)));
    void decisions
      .typologyTelemetry()
      .then(setTypology)
      .catch(() => setTypology(null));
    void decisions
      .backtestBeforePromotePosture()
      .then(setBacktestPosture)
      .catch(() => setBacktestPosture(null));
  }, [tenantId]);

  const cc = data?.champion_challenger;
  const labelGate = data?.label_gated_promote;
  const mcnemar = data?.mcnemar_promote_gate;
  const driftGate = data?.drift_promote_gate;
  const deskGate = data?.desk_promote_gate;

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-gray-100">Shadow vs primary</h1>
      <p className="text-sm text-gray-400">
        Label-gated promote + champion–challenger agreement. Warehouse diffs use the SQL recipe. L3 stays NOT
        STARTED until a named live tenant.
      </p>

      <label className="block text-xs text-gray-500 max-w-xs">
        Tenant for label / CC scan
        <input
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          className="mt-1 w-full bg-surface-900 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
        />
      </label>

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
        <section className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 space-y-3">
          <h2 className="text-sm font-semibold text-gray-200">Desk promote gate</h2>
          <p className="text-sm text-gray-300">
            Combined:{" "}
            <span
              className={
                deskGate?.promote_allowed ? "text-emerald-400 font-semibold" : "text-amber-300 font-semibold"
              }
            >
              {deskGate?.promote_allowed ? "allowed" : "blocked"}
            </span>
            {deskGate?.blockers?.length ? (
              <span className="text-xs text-gray-500 ml-2">[{deskGate.blockers.join(", ")}]</span>
            ) : null}
          </p>
          <dl className="grid gap-1 text-xs text-gray-400 sm:grid-cols-3 font-mono">
            <div>
              Labels:{" "}
              <span className={labelGate?.promote_allowed ? "text-emerald-400" : "text-amber-300"}>
                {labelGate?.promote_allowed ? "ok" : "blocked"}
              </span>
              {labelGate?.blockers?.length ? ` (${labelGate.blockers.join(", ")})` : ""}
            </div>
            <div>
              McNemar: {mcnemar?.discordant_pairs ?? 0}/{mcnemar?.min_discordant_pairs ?? 20} —{" "}
              <span className={mcnemar?.promote_allowed ? "text-emerald-400" : "text-amber-300"}>
                {mcnemar?.promote_allowed ? "ok" : "blocked"}
              </span>
            </div>
            <div>
              Drift: {driftGate?.drift_score ?? "n/a"} —{" "}
              <span className={driftGate?.promote_allowed ? "text-emerald-400" : "text-amber-300"}>
                {driftGate?.promote_allowed ? "ok" : "blocked"}
              </span>
              {driftGate?.hint ? ` (${driftGate.hint})` : ""}
            </div>
          </dl>
          <p className="text-xs text-gray-500">{data.honesty}</p>
          <div className="text-xs text-gray-400 space-y-1">
            <div>
              Kill smoke — underpowered: promote {data.blocked?.promote_allowed ? "allowed" : "blocked"}
            </div>
            <div>
              Kill smoke — healthy metrics: promote {data.allowed?.promote_allowed ? "allowed" : "blocked"}
            </div>
            <code className="text-[10px] text-gray-500">{data.recipe_path}</code>
          </div>
        </section>
      ) : null}

      {cc ? (
        <section
          className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 space-y-3"
          data-testid="champion-challenger-panel"
        >
          <h2 className="text-sm font-semibold text-gray-200">Champion–challenger agreement</h2>
          <dl className="grid gap-1 text-xs text-gray-300 sm:grid-cols-3 font-mono">
            <div>
              Rows with routing:{" "}
              <span className="text-gray-100">{cc.rows_with_policy_routing ?? 0}</span>
            </div>
            <div>
              Agree count: <span className="text-gray-100">{cc.decisions_agree_count ?? 0}</span>
            </div>
            <div>
              Agreement rate:{" "}
              <span className="text-gray-100">
                {cc.decision_agreement_rate == null ? "n/a" : cc.decision_agreement_rate}
              </span>
            </div>
          </dl>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] text-left text-gray-400">
              <thead>
                <tr className="border-b border-surface-700 text-gray-500">
                  <th className="py-1 pr-2">Trace</th>
                  <th className="py-1 pr-2">Champion</th>
                  <th className="py-1 pr-2">Challenger</th>
                  <th className="py-1">Agree</th>
                </tr>
              </thead>
              <tbody>
                {(cc.audit_rows || []).slice(0, 20).map((row, i) => (
                  <tr key={`${row.trace_id || i}`} className="border-b border-surface-800/80">
                    <td className="py-1 pr-2 font-mono text-gray-300">{row.trace_id || "—"}</td>
                    <td className="py-1 pr-2">{row.champion_decision}</td>
                    <td className="py-1 pr-2">{row.challenger_decision}</td>
                    <td className="py-1">{row.decisions_agree ? "yes" : "no"}</td>
                  </tr>
                ))}
                {!cc.audit_rows?.length ? (
                  <tr>
                    <td colSpan={4} className="py-2 text-gray-500">
                      No policy_routing rows yet — enable POLICY_CHAMPION_CHALLENGER and evaluate traffic.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {backtestPosture ? (
        <section
          className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 space-y-2"
          data-testid="backtest-before-promote-panel"
        >
          <h2 className="text-sm font-semibold text-gray-200">Backtest before promote</h2>
          <p className="text-xs text-gray-400">
            Required:{" "}
            <span className="font-mono text-gray-200">
              {backtestPosture.require_backtest_before_promote ? "yes" : "no (optional job id)"}
            </span>
          </p>
          <p className="text-[11px] text-gray-500">{backtestPosture.note}</p>
          <a href={backtestPosture.ui || "/ops/backtest"} className="text-xs text-brand-400 hover:text-brand-300">
            Open backtest jobs →
          </a>
        </section>
      ) : null}

      {typology ? (
        <section
          className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 space-y-3"
          data-testid="typology-telemetry-panel"
        >
          <h2 className="text-sm font-semibold text-gray-200">Typology weighted telemetry</h2>
          <p className="text-xs text-gray-500">
            {typology.aggregation?.mode} — {typology.aggregation?.note}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] text-left text-gray-400">
              <thead>
                <tr className="border-b border-surface-700 text-gray-500">
                  <th className="py-1 pr-2">Id</th>
                  <th className="py-1 pr-2">Weight/hit</th>
                  <th className="py-1 pr-2">Warn</th>
                  <th className="py-1">Alert</th>
                </tr>
              </thead>
              <tbody>
                {(typology.configured || []).slice(0, 12).map((t) => (
                  <tr key={t.id} className="border-b border-surface-800/80">
                    <td className="py-1 pr-2 font-mono text-gray-300">{t.id}</td>
                    <td className="py-1 pr-2">{t.weight_per_rule_hit}</td>
                    <td className="py-1 pr-2">{t.breach_thresholds?.warning}</td>
                    <td className="py-1">{t.breach_thresholds?.alert}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
