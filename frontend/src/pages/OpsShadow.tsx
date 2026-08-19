import { useEffect, useState } from "react";
import { decisions } from "../api/v1/decisions";
import { validateL3ArmInput } from "../workbench/l3LedgerArm";
import { toUserFacingError } from "../utils/userFacingErrors";

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
    p_value?: number | null;
    mid_p?: number | null;
    method?: string | null;
    alpha?: number;
  };
  labeled_champion_challenger_f1?: {
    labeled_rows?: number;
    champion_f1?: number | null;
    challenger_f1?: number | null;
    note?: string;
  };
  drift_promote_gate?: {
    promote_allowed?: boolean;
    blockers?: string[];
    drift_score?: number | null;
    psi?: number | null;
    max_psi?: number | null;
    hint?: string | null;
  };
  desk_promote_gate?: {
    promote_allowed?: boolean;
    blockers?: string[];
    requires?: string[];
  };
  promote_lifecycle?: {
    stage?: string;
    stages?: string[];
    gates?: Record<string, boolean>;
    note?: string;
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
  audit_breach_histogram?: {
    rows_with_typology_summary?: number;
    highest_breach_counts?: Record<string, number>;
    alert_or_warning_rows?: number;
    driver_typology_counts?: Record<string, number>;
  } | null;
};

type L3Ledger = {
  status?: string;
  tenant_id?: string | null;
  week1_start_utc?: string | null;
  week4_end_utc?: string | null;
  shadow_evaluate_enabled?: boolean;
  host_action_sink?: string | null;
  label_join_ece?: boolean;
  claim_allowed?: boolean;
  host_action_log_count?: number;
  internal_host_action_sink?: string;
  weeks?: Record<
    string,
    {
      shadow_on?: boolean;
      host_actions_logged?: boolean;
      outcomes_joined?: boolean;
      weekly_metrics?: boolean;
      ece_candidate?: boolean;
      sign_off?: boolean;
    }
  >;
  honesty?: string;
  playbook?: string;
};

const L3_WEEK_ROWS = [1, 2, 3, 4] as const;

function todayUtcDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function OpsShadow() {
  const [tenantId, setTenantId] = useState("demo");
  const [data, setData] = useState<ShadowPromoteGate | null>(null);
  const [typology, setTypology] = useState<TypologyTelemetry | null>(null);
  const [l3, setL3] = useState<L3Ledger | null>(null);
  const [backtestPosture, setBacktestPosture] = useState<{
    require_backtest_before_promote?: boolean;
    note?: string;
    ui?: string;
  } | null>(null);
  const [err, setErr] = useState("");
  const [l3ArmTenant, setL3ArmTenant] = useState("");
  const [l3ArmWeek1, setL3ArmWeek1] = useState(todayUtcDate());
  const [l3ArmSink, setL3ArmSink] = useState("");
  const [l3Msg, setL3Msg] = useState("");
  const [l3Busy, setL3Busy] = useState(false);
  const [signWeek, setSignWeek] = useState<1 | 2 | 3 | 4>(1);
  const [signEce, setSignEce] = useState(false);

  async function refreshL3() {
    try {
      const view = await decisions.l3Ledger();
      setL3(view);
      if (!l3ArmSink && view.internal_host_action_sink) {
        setL3ArmSink(view.internal_host_action_sink);
      }
    } catch {
      setL3(null);
    }
  }

  useEffect(() => {
    void decisions
      .shadowPromoteGate(tenantId)
      .then(setData)
      .catch((e) => setErr(String(e)));
    void decisions
      .typologyOps(tenantId)
      .then((ops) =>
        setTypology({
          typology_count: ops.control_plane?.typology_count,
          configured: ops.configured,
          aggregation: {
            mode: ops.control_plane?.aggregation,
            note: ops.vs_tazama || ops.honesty,
          },
          audit_breach_histogram: ops.audit_breach_histogram ?? null,
        }),
      )
      .catch(() => setTypology(null));
    void decisions
      .backtestBeforePromotePosture()
      .then(setBacktestPosture)
      .catch(() => setBacktestPosture(null));
    void refreshL3();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh L3 once + when promote tenant changes
  }, [tenantId]);

  const cc = data?.champion_challenger;
  const labelGate = data?.label_gated_promote;
  const mcnemar = data?.mcnemar_promote_gate;
  const driftGate = data?.drift_promote_gate;
  const deskGate = data?.desk_promote_gate;
  const lifecycle = data?.promote_lifecycle;
  const l3Status = l3?.status || "NOT_STARTED";
  const l3Armed = l3Status !== "NOT_STARTED" && Boolean(l3?.tenant_id);

  async function armL3() {
    setL3Msg("");
    const sink = l3ArmSink.trim() || l3?.internal_host_action_sink || "";
    const body = {
      tenant_id: l3ArmTenant.trim(),
      week1_start_utc: l3ArmWeek1.trim(),
      host_action_sink: sink,
      shadow_evaluate_enabled: true,
      actor: "ops-shadow-ui",
    };
    const blockers = validateL3ArmInput(body);
    if (blockers.length) {
      setL3Msg(`Blocked: ${blockers.join(", ")}`);
      return;
    }
    setL3Busy(true);
    try {
      const out = await decisions.l3LedgerArm(body);
      setL3(out.ledger as L3Ledger);
      setL3Msg("L3 armed — clock started (claim still locked until COMPLETE).");
    } catch (e) {
      setL3Msg(toUserFacingError(e, { subject: "L3 ledger", action: "arm four-week clock" }));
    } finally {
      setL3Busy(false);
    }
  }

  async function signL3Week() {
    setL3Msg("");
    setL3Busy(true);
    try {
      const out = await decisions.l3LedgerSignWeek(signWeek, {
        shadow_on: true,
        host_actions_logged: true,
        outcomes_joined: true,
        weekly_metrics: true,
        ece_candidate: signWeek === 4 ? signEce : false,
        sign_off: true,
        actor: "ops-shadow-ui",
      });
      setL3(out.ledger as L3Ledger);
      setL3Msg(`Week ${signWeek} signed.`);
    } catch (e) {
      setL3Msg(toUserFacingError(e, { subject: "L3 ledger", action: `sign week ${signWeek}` }));
    } finally {
      setL3Busy(false);
    }
  }

  async function logSampleHostAction() {
    const tid = (l3?.tenant_id || l3ArmTenant).trim();
    if (!tid) {
      setL3Msg("Set armed tenant or arm form tenant before logging host actions.");
      return;
    }
    setL3Busy(true);
    setL3Msg("");
    try {
      await decisions.hostActionLog({
        tenant_id: tid,
        action: "challenge_issued",
        actor: "ops-shadow-ui",
      });
      await refreshL3();
      setL3Msg("Host action appended to internal JSONL sink.");
    } catch (e) {
      setL3Msg(toUserFacingError(e, { subject: "Host actions", action: "append sample action" }));
    } finally {
      setL3Busy(false);
    }
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-gray-100">Observe vs primary</h1>
      <p className="text-sm text-gray-400">
        Outcome-loop surfaces: L3 live ledger + label/McNemar/drift desk promote. Sim never starts L3.
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
            {l3Status}
          </span>
        </div>
        <p className="text-xs text-amber-100/85 leading-relaxed">
          {l3?.honesty ||
            "Arm via POST /v1/ops/l3-ledger/arm with a named live tenant + host action sink. Sim never advances this ledger."}
        </p>
        <dl className="grid gap-1 text-[11px] text-gray-300 sm:grid-cols-2 font-mono">
          <div>
            Tenant id: <span className="text-gray-100">{l3?.tenant_id || "pending operator"}</span>
          </div>
          <div>
            Week 1 start (UTC): <span className="text-gray-100">{l3?.week1_start_utc || "not set"}</span>
          </div>
          <div>
            Observe evaluate:{" "}
            <span className="text-gray-100">{l3?.shadow_evaluate_enabled ? "yes" : "no"}</span>
          </div>
          <div>
            Host action sink:{" "}
            <span className="text-gray-100 break-all">{l3?.host_action_sink || "no"}</span>
          </div>
          <div>
            Host actions logged: <span className="text-gray-100">{l3?.host_action_log_count ?? 0}</span>
          </div>
          <div>
            Label join / ECE: <span className="text-gray-100">{l3?.label_join_ece ? "yes" : "no"}</span>
          </div>
          <div>
            Claim allowed:{" "}
            <span className={l3?.claim_allowed ? "text-emerald-300" : "text-amber-200"}>
              {l3?.claim_allowed ? "yes" : "no"}
            </span>
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
              {L3_WEEK_ROWS.map((w) => {
                const row = l3?.weeks?.[String(w)];
                return (
                  <tr key={w} className="border-b border-surface-800/80">
                    <td className="py-1 pr-2 font-mono text-gray-300">{w}</td>
                    <td className="py-1 pr-2">{row?.shadow_on ? "☑" : "☐"}</td>
                    <td className="py-1 pr-2">{row?.host_actions_logged ? "☑" : "☐"}</td>
                    <td className="py-1 pr-2">{row?.outcomes_joined ? "☑" : "☐"}</td>
                    <td className="py-1 pr-2">{row?.weekly_metrics ? "☑" : "☐"}</td>
                    <td className="py-1">{row?.sign_off ? "☑" : "☐"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!l3Armed ? (
          <div className="space-y-2 border-t border-amber-500/20 pt-3" data-testid="l3-arm-form">
            <p className="text-[11px] text-amber-100/80">
              Arm the live clock (admin). Rejects <span className="font-mono">demo</span>/sim tenants and sim
              sinks. Arming ≠ COMPLETE claim.
            </p>
            <div className="grid gap-2 sm:grid-cols-3">
              <label className="block text-[10px] text-gray-500">
                Live tenant id
                <input
                  value={l3ArmTenant}
                  onChange={(e) => setL3ArmTenant(e.target.value)}
                  placeholder="acme-prod"
                  className="mt-1 w-full bg-surface-900 border border-surface-600 rounded-lg px-2 py-1.5 text-xs text-gray-200 font-mono"
                />
              </label>
              <label className="block text-[10px] text-gray-500">
                Week 1 start (UTC)
                <input
                  type="date"
                  value={l3ArmWeek1}
                  onChange={(e) => setL3ArmWeek1(e.target.value)}
                  className="mt-1 w-full bg-surface-900 border border-surface-600 rounded-lg px-2 py-1.5 text-xs text-gray-200 font-mono"
                />
              </label>
              <label className="block text-[10px] text-gray-500 sm:col-span-1">
                Host action sink
                <input
                  value={l3ArmSink}
                  onChange={(e) => setL3ArmSink(e.target.value)}
                  placeholder={l3?.internal_host_action_sink || "internal:jsonl:…"}
                  className="mt-1 w-full bg-surface-900 border border-surface-600 rounded-lg px-2 py-1.5 text-xs text-gray-200 font-mono"
                />
              </label>
            </div>
            <button
              type="button"
              disabled={l3Busy}
              onClick={() => void armL3()}
              className="text-xs px-3 py-1.5 rounded border border-amber-500/50 text-amber-100 hover:bg-amber-500/10 disabled:opacity-50"
            >
              {l3Busy ? "Arming…" : "Arm L3 clock (admin)"}
            </button>
          </div>
        ) : (
          <div className="space-y-2 border-t border-amber-500/20 pt-3" data-testid="l3-sign-form">
            <p className="text-[11px] text-amber-100/80">
              Sign a completed live week (admin). Week 4 requires ECE on real labels.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <label className="block text-[10px] text-gray-500">
                Week
                <select
                  value={signWeek}
                  onChange={(e) => setSignWeek(Number(e.target.value) as 1 | 2 | 3 | 4)}
                  className="mt-1 block bg-surface-900 border border-surface-600 rounded-lg px-2 py-1.5 text-xs text-gray-200"
                >
                  {L3_WEEK_ROWS.map((w) => (
                    <option key={w} value={w}>
                      {w}
                    </option>
                  ))}
                </select>
              </label>
              {signWeek === 4 ? (
                <label className="flex items-center gap-2 text-[11px] text-gray-300 pb-1">
                  <input
                    type="checkbox"
                    checked={signEce}
                    onChange={(e) => setSignEce(e.target.checked)}
                  />
                  ECE candidate on real labels
                </label>
              ) : null}
              <button
                type="button"
                disabled={l3Busy}
                onClick={() => void signL3Week()}
                className="text-xs px-3 py-1.5 rounded border border-amber-500/50 text-amber-100 hover:bg-amber-500/10 disabled:opacity-50"
              >
                {l3Busy ? "Signing…" : `Sign week ${signWeek}`}
              </button>
              <button
                type="button"
                disabled={l3Busy}
                onClick={() => void logSampleHostAction()}
                className="text-xs px-3 py-1.5 rounded border border-surface-600 text-gray-200 hover:border-brand-500 disabled:opacity-50"
              >
                Log sample host action
              </button>
            </div>
          </div>
        )}

        {l3Msg ? <p className="text-[11px] font-mono text-amber-100/90">{l3Msg}</p> : null}
        <p className="text-[10px] text-gray-500 font-mono">
          {l3?.playbook || "docs/compliance/CLAIM_LOCK.md"}
          {l3?.internal_host_action_sink ? ` · sink ${l3.internal_host_action_sink}` : ""}
        </p>
      </section>

      {err ? <p className="text-red-400">{err}</p> : null}
      {data ? (
        <section className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-200">Desk promote gate</h2>
            {lifecycle?.stage ? (
              <span
                className="text-[10px] font-bold uppercase tracking-wide rounded-full border border-brand-500/40 bg-brand-500/10 px-2 py-0.5 text-brand-200"
                data-testid="promote-lifecycle-stage"
              >
                {lifecycle.stage}
              </span>
            ) : null}
          </div>
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
          {lifecycle?.note ? <p className="text-[11px] text-gray-500">{lifecycle.note}</p> : null}
          {driftGate?.psi != null ? (
            <p className="text-[11px] font-mono text-gray-500">
              PSI {driftGate.psi}
              {driftGate.max_psi != null ? ` (max ${driftGate.max_psi})` : ""}
            </p>
          ) : null}
          {data.labeled_champion_challenger_f1?.labeled_rows ? (
            <p className="text-[11px] font-mono text-gray-500">
              Labeled F1 champ={data.labeled_champion_challenger_f1.champion_f1 ?? "n/a"} / chall=
              {data.labeled_champion_challenger_f1.challenger_f1 ?? "n/a"} (n=
              {data.labeled_champion_challenger_f1.labeled_rows})
            </p>
          ) : null}
          <dl className="grid gap-1 text-xs text-gray-400 sm:grid-cols-3 font-mono">
            <div>
              Labels:{" "}
              <span className={labelGate?.promote_allowed ? "text-emerald-400" : "text-amber-300"}>
                {labelGate?.promote_allowed ? "ok" : "blocked"}
              </span>
            </div>
            <div>
              McNemar: {mcnemar?.discordant_pairs ?? 0}/{mcnemar?.min_discordant_pairs ?? 20}
              {mcnemar?.mid_p != null ? ` mid-p=${mcnemar.mid_p}` : ""} —{" "}
              <span className={mcnemar?.promote_allowed ? "text-emerald-400" : "text-amber-300"}>
                {mcnemar?.promote_allowed ? "ok" : "blocked"}
              </span>
            </div>
            <div>
              Drift: {driftGate?.drift_score ?? "n/a"} —{" "}
              <span className={driftGate?.promote_allowed ? "text-emerald-400" : "text-amber-300"}>
                {driftGate?.promote_allowed ? "ok" : "blocked"}
              </span>
            </div>
          </dl>
          <p className="text-xs text-gray-500">{data.honesty}</p>
          <div className="text-xs text-gray-400 space-y-1">
            <div>Kill smoke — underpowered: promote {data.blocked?.promote_allowed ? "allowed" : "blocked"}</div>
            <div>Kill smoke — healthy metrics: promote {data.allowed?.promote_allowed ? "allowed" : "blocked"}</div>
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
              Rows with routing: <span className="text-gray-100">{cc.rows_with_policy_routing ?? 0}</span>
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
          {typology.audit_breach_histogram ? (
            <p className="text-[11px] font-mono text-gray-500">
              Audit breaches:{" "}
              {JSON.stringify(typology.audit_breach_histogram.highest_breach_counts || {})} — alert/warn{" "}
              {typology.audit_breach_histogram.alert_or_warning_rows ?? 0}/
              {typology.audit_breach_histogram.rows_with_typology_summary ?? 0}
            </p>
          ) : null}
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
