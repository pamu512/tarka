import { useEffect, useState } from "react";
import { decisions } from "../api/v1/decisions";
import { PageTitle } from "../components/PageTitle";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

type ReliabilityBins = {
  schema_id?: string;
  labeled_rows?: number;
  proxy_label_rows?: number;
  label_source?: string;
  caveat?: string | null;
  posture?: { healthy?: boolean; status?: string; hint?: string; label_coverage?: number };
  bins?: Array<Record<string, unknown>>;
};

type FixtureVerticalCal = {
  vertical: string;
  ok?: boolean;
  n?: number;
  expected_calibration_error?: number | null;
  drift_flag?: string;
  promote_f1?: number;
  reliability_bins?: Array<Record<string, unknown>>;
  honesty?: string;
};

export default function OpsCalibration() {
  const { tenantId } = useTenantEnvironment();
  const [profile, setProfile] = useState("default");
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [drift, setDrift] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<Array<Record<string, unknown>>>([]);
  const [bins, setBins] = useState<ReliabilityBins | null>(null);
  const [fixtureCal, setFixtureCal] = useState<{
    any_drift_elevated?: boolean;
    verticals: FixtureVerticalCal[];
  } | null>(null);
  const [fixtureErr, setFixtureErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);

  useEffect(() => {
    setFixtureErr(null);
    void (async () => {
      try {
        const body = await decisions.verticalCalibrationPosture();
        setFixtureCal({
          any_drift_elevated: body.any_drift_elevated,
          verticals: (body.verticals ?? []) as FixtureVerticalCal[],
        });
      } catch (e) {
        setFixtureErr(
          toUserFacingError(e, {
            subject: "Fixture vertical calibration",
            action: "load /v1/ops/vertical-calibration",
          }),
        );
        setFixtureCal(null);
      }
    })();
  }, []);

  useEffect(() => {
    if (!tenantId.trim()) return;
    setErr(null);
    (async () => {
      try {
        const [st, d, sum] = await Promise.all([
          decisions.calibrationStatus(tenantId.trim(), profile.trim() || "default"),
          decisions.calibrationDrift(tenantId.trim(), profile.trim() || "default"),
          decisions.calibrationSummary(tenantId.trim(), profile.trim() || "default", 12),
        ]);
        setStatus(st as Record<string, unknown>);
        setDrift(d);
        setSummary((sum.snapshots as Array<Record<string, unknown>>) ?? []);
      } catch (e) {
        setErr(toUserFacingError(e, { subject: "Calibration data", action: "load calibration and drift data" }));
        setStatus(null);
        setDrift(null);
        setSummary([]);
      }
    })();
  }, [tenantId, profile]);

  async function loadBins() {
    setErr(null);
    try {
      const out = await decisions.reliabilityBins(tenantId.trim(), 5000, 10);
      setBins(out as ReliabilityBins);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Reliability bins", action: "load reliability bins" }));
      setBins(null);
    }
  }

  async function downloadCsv() {
    setExportBusy(true);
    setErr(null);
    try {
      const csv = await decisions.reliabilityExportCsv(tenantId.trim(), 10_000);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = `reliability_${tenantId.trim() || "tenant"}.csv`;
      a.click();
      URL.revokeObjectURL(href);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Reliability CSV", action: "download reliability export" }));
    } finally {
      setExportBusy(false);
    }
  }

  const cal = (status?.calibration as Record<string, unknown> | undefined) ?? {};
  const binRows = bins?.bins ?? [];

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="analytics">Calibration &amp; drift</PageTitle>
        <p className="text-sm text-gray-500">
          Same data as{" "}
          <span className="font-mono text-xs text-gray-400">GET /v1/ops/calibration-status</span> and{" "}
          <span className="font-mono text-xs text-gray-400">/v1/calibration/*</span> — file-backed snapshots for ops.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm text-gray-400">
          Profile
          <input
            className="ml-2 rounded-lg border border-surface-600 bg-surface-900 px-2 py-1 text-gray-200 font-mono text-sm"
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
          />
        </label>
        <span className="text-xs text-gray-600">
          Tenant: <span className="font-mono text-brand-300">{tenantId || "(set in header)"}</span>
        </span>
      </div>

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300 space-y-1">
          <p>{err}</p>
          <SupportIdHint
            message={err}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}

      {status?.healthy === false || bins?.posture?.healthy === false ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
          Calibration posture unhealthy — join dispositions into{" "}
          <span className="font-mono text-xs">y_label</span> (proxy-only is not enough for promote).{" "}
          {String(bins?.posture?.hint ?? status?.hint ?? "")}
        </div>
      ) : null}
      {status?.healthy === true || bins?.posture?.healthy === true ? (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">
          Calibration posture healthy
          {bins?.posture?.label_coverage != null
            ? ` · label coverage ${bins.posture.label_coverage}`
            : ""}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <h3 className="text-gray-300 font-medium mb-2">Ops status</h3>
          <dl className="space-y-1 text-gray-400">
            <div>
              Profile: <span className="font-mono text-brand-300">{profile || "default"}</span>
            </div>
            <div>
              Inference schema:{" "}
              <span className="font-mono text-brand-300">{String(status?.inference_schema_version ?? "—")}</span>
            </div>
            <div>
              Challenge policy default:{" "}
              <span className="font-mono text-gray-300">{String(status?.challenge_policy_default ?? "—")}</span>
            </div>
          </dl>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <h3 className="text-gray-300 font-medium mb-2">Drift hint</h3>
          <dl className="space-y-1 text-gray-400">
            <div>
              Score:{" "}
              <span className="font-mono text-brand-300">
                {cal.drift_score != null ? String(cal.drift_score) : "—"}
              </span>
            </div>
            <div>
              Hint: <span className="text-gray-200">{String(cal.hint ?? drift?.hint ?? "—")}</span>
            </div>
            <div className="text-xs text-gray-600">
              Latest: {String(cal.latest_ts ?? "—")} · Reference: {String(cal.reference_set_at ?? "—")}
            </div>
          </dl>
        </div>
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-medium text-gray-300">Reliability bins / export</h3>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void loadBins()}
              className="px-3 py-1.5 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200"
            >
              Load bins
            </button>
            <button
              type="button"
              disabled={exportBusy || !tenantId.trim()}
              onClick={() => void downloadCsv()}
              className="px-3 py-1.5 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200 disabled:opacity-50"
            >
              {exportBusy ? "Downloading…" : "Download CSV"}
            </button>
          </div>
        </div>
        {bins?.caveat ? <p className="text-xs text-amber-200/80">{bins.caveat}</p> : null}
        {bins ? (
          <p className="text-xs text-gray-500">
            {String(bins.schema_id ?? "")} · labeled {String(bins.labeled_rows ?? 0)} · source{" "}
            <span className="font-mono">{String(bins.label_source ?? "—")}</span>
          </p>
        ) : (
          <p className="text-xs text-gray-500">Load bins from recent decision_audit (proxy labels unless y_label filled).</p>
        )}
        {binRows.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-surface-700">
            <table className="min-w-full text-sm">
              <thead className="bg-surface-800 text-left text-gray-400">
                <tr>
                  <th className="px-3 py-2">Bin</th>
                  <th className="px-3 py-2">n</th>
                  <th className="px-3 py-2">Mean score</th>
                  <th className="px-3 py-2">Positive rate</th>
                </tr>
              </thead>
              <tbody>
                {binRows.map((b, i) => (
                  <tr key={i} className="border-t border-surface-700/80">
                    <td className="px-3 py-2 font-mono text-xs text-brand-300">
                      {String(b.lo ?? "")}–{String(b.hi ?? "")}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-gray-400">{String(b.n ?? 0)}</td>
                    <td className="px-3 py-2 tabular-nums text-gray-400">{String(b.mean_score ?? "—")}</td>
                    <td className="px-3 py-2 tabular-nums text-gray-400">{String(b.positive_rate ?? "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="rounded-xl border border-surface-700 overflow-hidden">
        <div className="bg-surface-800 px-3 py-2 text-xs font-medium text-gray-400">Recent snapshots</div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-surface-900 text-left text-gray-500">
              <tr>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Samples</th>
                <th className="px-3 py-2">Mean integrity</th>
                <th className="px-3 py-2">Mean score</th>
                <th className="px-3 py-2">Notes</th>
              </tr>
            </thead>
            <tbody>
              {summary.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-gray-500">
                    No snapshots for this tenant/profile yet. POST to{" "}
                    <span className="font-mono text-xs">/v1/calibration/snapshots</span> from your ETL or batch job.
                  </td>
                </tr>
              ) : (
                summary.map((row, i) => (
                  <tr key={i} className="border-t border-surface-700/80">
                    <td className="px-3 py-2 font-mono text-xs text-gray-300">{String(row.ts ?? "")}</td>
                    <td className="px-3 py-2 tabular-nums text-gray-400">{String(row.sample_count ?? "—")}</td>
                    <td className="px-3 py-2 tabular-nums text-gray-400">{String(row.mean_integrity ?? "—")}</td>
                    <td className="px-3 py-2 tabular-nums text-gray-400">{String(row.mean_final_score ?? "—")}</td>
                    <td className="px-3 py-2 text-gray-500 max-w-md truncate" title={String(row.notes ?? "")}>
                      {String(row.notes ?? "—")}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-medium text-gray-300">Fixture vertical ECE (offline)</h3>
          <span className="text-[10px] uppercase tracking-wide text-amber-200/90">
            Not LIVE calibration
          </span>
        </div>
        <p className="text-xs text-gray-500">
          Holdout reliability bins from{" "}
          <span className="font-mono text-gray-400">GET /v1/ops/vertical-calibration</span>. Synthetic
          labels only — promote stays fixture-gated; never claim tenant-calibrated risk.
        </p>
        {fixtureErr ? (
          <p className="text-xs text-red-300">{fixtureErr}</p>
        ) : null}
        {fixtureCal?.any_drift_elevated ? (
          <p className="text-xs text-amber-200">
            One or more verticals show elevated/critical fixture ECE drift (CI kill on critical).
          </p>
        ) : null}
        {(fixtureCal?.verticals ?? []).map((v) => {
          const rows = v.reliability_bins ?? [];
          return (
            <div key={v.vertical} className="space-y-2 border-t border-surface-700/80 pt-3">
              <div className="flex flex-wrap gap-3 text-xs text-gray-400">
                <span className="font-mono text-brand-300">{v.vertical}</span>
                <span>
                  ECE{" "}
                  <span className="tabular-nums text-gray-200">
                    {v.expected_calibration_error != null
                      ? String(v.expected_calibration_error)
                      : "—"}
                  </span>
                </span>
                <span>
                  drift{" "}
                  <span
                    className={
                      v.drift_flag === "critical"
                        ? "text-red-300"
                        : v.drift_flag === "elevated"
                          ? "text-amber-200"
                          : "text-gray-200"
                    }
                  >
                    {String(v.drift_flag ?? "—")}
                  </span>
                </span>
                <span>
                  F1{" "}
                  <span className="tabular-nums text-gray-200">
                    {v.promote_f1 != null ? String(v.promote_f1) : "—"}
                  </span>
                </span>
                <span>
                  n <span className="tabular-nums text-gray-200">{String(v.n ?? 0)}</span>
                </span>
              </div>
              {rows.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border border-surface-700">
                  <table className="min-w-full text-sm">
                    <thead className="bg-surface-800 text-left text-gray-400">
                      <tr>
                        <th className="px-3 py-2">Bin</th>
                        <th className="px-3 py-2">n</th>
                        <th className="px-3 py-2">Mean score</th>
                        <th className="px-3 py-2">Positive rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((b, i) => (
                        <tr key={`${v.vertical}-${i}`} className="border-t border-surface-700/80">
                          <td className="px-3 py-2 font-mono text-xs text-brand-300">
                            {String(b.lo ?? "")}–{String(b.hi ?? "")}
                          </td>
                          <td className="px-3 py-2 tabular-nums text-gray-400">{String(b.n ?? 0)}</td>
                          <td className="px-3 py-2 tabular-nums text-gray-400">
                            {String(b.mean_score ?? "—")}
                          </td>
                          <td className="px-3 py-2 tabular-nums text-gray-400">
                            {String(b.positive_rate ?? "—")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-gray-600">No reliability bins for this vertical.</p>
              )}
            </div>
          );
        })}
      </div>

      <p className="text-xs text-gray-500">
        Runbook: <span className="font-mono">docs/docs/guides/calibration-ops-runbook.md</span>. Pin a reference with{" "}
        <span className="font-mono">POST /v1/calibration/reference/{"{profile}"}</span>.
      </p>

      <TrendOpsPanel tenantId={tenantId} />
    </div>
  );
}

type TrendDraft = {
  id?: string;
  entity_id?: string;
  status?: string;
  gitops_ready?: boolean;
  rule_package?: Record<string, unknown>;
  created_at?: number;
};

function TrendOpsPanel({ tenantId }: { tenantId: string }) {
  const [drafts, setDrafts] = useState<TrendDraft[]>([]);
  const [tickSummary, setTickSummary] = useState<string | null>(null);
  const [postureLine, setPostureLine] = useState<string | null>(null);
  const [trendErr, setTrendErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hilEntity, setHilEntity] = useState("");
  const [hilType, setHilType] = useState("ALLOW_SEASONAL_SPIKE");
  const [hilNote, setHilNote] = useState("");
  const [jobIds, setJobIds] = useState<Record<string, string>>({});

  async function loadDrafts() {
    if (!tenantId.trim()) return;
    setTrendErr(null);
    try {
      const [body, posture] = await Promise.all([
        decisions.trendDrafts(tenantId.trim()),
        decisions.trendPosture(tenantId.trim()).catch(() => null),
      ]);
      setDrafts((body.drafts ?? []) as TrendDraft[]);
      if (posture) {
        setPostureLine(
          `watch=${String(posture.watch_count ?? 0)} pending=${String(posture.pending_draft_count ?? 0)} ` +
            `min_n=${String(posture.baseline_min_n ?? "—")} promote=${String(posture.wasm_auto_promote ?? false)}`,
        );
      }
    } catch (e) {
      setTrendErr(
        toUserFacingError(e, { subject: "Trend drafts", action: "load /v1/ops/trend/drafts" }),
      );
      setDrafts([]);
    }
  }

  useEffect(() => {
    void loadDrafts();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when tenant changes
  }, [tenantId]);

  async function runTick() {
    setBusy(true);
    setTrendErr(null);
    try {
      const out = await decisions.trendTick({
        tenant_id: tenantId.trim(),
        limit: 25,
        skip_llm: true,
      });
      setTickSummary(
        `evaluated=${out.evaluated} skipped=${out.skipped} skip_llm=${String(out.skip_llm)}`,
      );
      await loadDrafts();
    } catch (e) {
      setTrendErr(toUserFacingError(e, { subject: "Trend tick", action: "POST /v1/ops/trend/tick" }));
    } finally {
      setBusy(false);
    }
  }

  async function rejectDraft(id: string) {
    setBusy(true);
    setTrendErr(null);
    try {
      await decisions.trendRejectDraft(id, tenantId.trim());
      await loadDrafts();
    } catch (e) {
      setTrendErr(toUserFacingError(e, { subject: "Trend reject", action: "reject draft" }));
    } finally {
      setBusy(false);
    }
  }

  async function promoteDraft(id: string) {
    const jobId = (jobIds[id] ?? "").trim();
    if (!jobId) return;
    setBusy(true);
    setTrendErr(null);
    try {
      await decisions.trendPromoteDraft(id, tenantId.trim(), jobId);
      await loadDrafts();
    } catch (e) {
      setTrendErr(
        toUserFacingError(e, { subject: "Trend promote", action: "POST /v1/ops/trend/drafts/{id}/promote" }),
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitHil() {
    if (!hilEntity.trim()) return;
    setBusy(true);
    setTrendErr(null);
    try {
      await decisions.trendHilOverride({
        tenant_id: tenantId.trim(),
        entity_id: hilEntity.trim(),
        override_type: hilType.trim() || "ALLOW_SEASONAL_SPIKE",
        analyst_rationale: hilNote.trim(),
      });
      setHilNote("");
    } catch (e) {
      setTrendErr(toUserFacingError(e, { subject: "HIL override", action: "POST hil-override" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-10 space-y-4 rounded-xl border border-surface-700 bg-surface-900/40 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-200">Trend agent (PENDING_VALIDATION)</h2>
        <span className="font-mono text-xs text-gray-500">/v1/ops/trend/*</span>
      </div>
      <p className="text-xs text-gray-500">
        Drafts are never Wasm-promotable. Tick uses EWMA baselines (never invents means) and defaults to{" "}
        <span className="font-mono">skip_llm</span>.
      </p>
      <p className="text-xs text-gray-500">Does not install live Wasm. Status stays PENDING_VALIDATION.</p>
      {trendErr ? <p className="text-sm text-red-300">{trendErr}</p> : null}
      {postureLine ? <p className="font-mono text-xs text-gray-400">{postureLine}</p> : null}
      {tickSummary ? <p className="font-mono text-xs text-brand-300">{tickSummary}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || !tenantId.trim()}
          onClick={() => void runTick()}
          className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm text-white disabled:opacity-40"
        >
          Run tick
        </button>
        <button
          type="button"
          disabled={busy || !tenantId.trim()}
          onClick={() => void loadDrafts()}
          className="rounded-lg border border-surface-600 px-3 py-1.5 text-sm text-gray-200 disabled:opacity-40"
        >
          Refresh drafts
        </button>
      </div>
      <div className="space-y-2">
        {drafts.length === 0 ? (
          <p className="text-xs text-gray-600">No pending drafts for this tenant.</p>
        ) : (
          drafts.map((d) => (
            <div
              key={String(d.id)}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-700 px-3 py-2 text-sm"
            >
              <div className="min-w-0 font-mono text-xs text-gray-300">
                <div>{String(d.entity_id ?? "—")}</div>
                <div className="text-gray-500">{String(d.id ?? "")}</div>
                <div className="text-gray-500">
                  wasm_ready={String((d.rule_package as { wasm_ready?: boolean } | undefined)?.wasm_ready ?? false)}
                </div>
                <div className="text-gray-500">gitops_ready={String(d.gitops_ready ?? false)}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  className="w-40 rounded border border-surface-600 bg-surface-950 px-2 py-1 text-xs text-gray-200"
                  placeholder="backtest_job_id"
                  value={d.id ? (jobIds[d.id] ?? "") : ""}
                  disabled={busy || !d.id}
                  onChange={(e) => {
                    if (!d.id) return;
                    setJobIds((prev) => ({ ...prev, [d.id as string]: e.target.value }));
                  }}
                />
                <button
                  type="button"
                  disabled={busy || !d.id || !(jobIds[String(d.id)] ?? "").trim()}
                  onClick={() => d.id && void promoteDraft(String(d.id))}
                  className="rounded border border-brand-500/40 bg-brand-600/80 px-2 py-1 text-xs text-white disabled:opacity-40"
                >
                  Mark GitOps-ready
                </button>
                <button
                  type="button"
                  disabled={busy || !d.id}
                  onClick={() => d.id && void rejectDraft(String(d.id))}
                  className="rounded border border-red-800/60 px-2 py-1 text-xs text-red-200 disabled:opacity-40"
                >
                  Reject
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <div className="grid gap-2 border-t border-surface-700 pt-3 sm:grid-cols-2">
        <input
          className="rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200"
          placeholder="entity_id for HIL"
          value={hilEntity}
          onChange={(e) => setHilEntity(e.target.value)}
        />
        <input
          className="rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200"
          placeholder="override_type"
          value={hilType}
          onChange={(e) => setHilType(e.target.value)}
        />
        <input
          className="sm:col-span-2 rounded border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200"
          placeholder="analyst rationale"
          value={hilNote}
          onChange={(e) => setHilNote(e.target.value)}
        />
        <button
          type="button"
          disabled={busy || !tenantId.trim() || !hilEntity.trim()}
          onClick={() => void submitHil()}
          className="rounded-lg border border-surface-600 px-3 py-1.5 text-sm text-gray-200 disabled:opacity-40 sm:col-span-2"
        >
          Record HIL override
        </button>
      </div>
    </div>
  );
}
