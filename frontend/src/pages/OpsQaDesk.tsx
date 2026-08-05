import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { cases } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

type QaMetrics = {
  pending?: number;
  reviewed?: number;
  agree?: number;
  disagree?: number;
  agreement_rate?: number | null;
  disagreement_rate?: number | null;
};

type CaseRow = {
  id: string;
  status?: string;
  labels?: string[];
  entity_id?: string;
};

export default function OpsQaDesk() {
  const { tenantId } = useTenantEnvironment();
  const [metrics, setMetrics] = useState<QaMetrics | null>(null);
  const [pending, setPending] = useState<CaseRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastSample, setLastSample] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!tenantId.trim()) return;
    setErr(null);
    try {
      const [m, list] = await Promise.all([
        cases.qaMetrics(tenantId.trim()),
        cases.list({ tenant_id: tenantId.trim(), limit: 100 }),
      ]);
      setMetrics(m);
      const rows = (list.items || []) as CaseRow[];
      setPending(
        rows.filter(
          (c) =>
            (c.labels || []).includes("qa:pending") &&
            !(c.labels || []).some(
              (l) => String(l).startsWith("qa:agree") || String(l).startsWith("qa:disagree"),
            ),
        ),
      );
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "QA desk", action: "load QA metrics and cases" }));
      setMetrics(null);
      setPending([]);
    }
  }, [tenantId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runSample() {
    setBusy(true);
    setErr(null);
    try {
      const out = await cases.qaSample(tenantId.trim(), { rate: 0.1, limit: 20 });
      setLastSample(`queued ${out.queued.length} / sampled ${out.sampled} (candidates ${out.candidates})`);
      await refresh();
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "QA sample", action: "sample closed cases" }));
    } finally {
      setBusy(false);
    }
  }

  async function review(caseId: string, original: string, qaStatus: string) {
    setBusy(true);
    setErr(null);
    try {
      await cases.qaReview({
        case_id: caseId,
        qa_status: qaStatus,
        original_status: original,
      });
      await refresh();
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "QA review", action: "submit QA disposition" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="cases">QA sampling desk</PageTitle>
        <p className="text-sm text-gray-500">
          Second-review queue from{" "}
          <span className="font-mono text-xs text-gray-400">GET /v1/cases/ops/qa-*</span> — sample
          closed cases, record agree/disagree.
        </p>
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

      <div className="grid gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">Pending QA</div>
          <div className="text-2xl font-mono text-brand-300">{metrics?.pending ?? "—"}</div>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">Reviewed</div>
          <div className="text-2xl font-mono text-gray-200">{metrics?.reviewed ?? "—"}</div>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">Agreement rate</div>
          <div className="text-2xl font-mono text-gray-200">
            {metrics?.agreement_rate != null ? `${Math.round(metrics.agreement_rate * 100)}%` : "—"}
          </div>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm flex flex-col justify-between gap-2">
          <button
            type="button"
            disabled={busy || !tenantId.trim()}
            onClick={() => void runSample()}
            className="px-3 py-2 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200 disabled:opacity-50"
          >
            {busy ? "Working…" : "Sample closed cases"}
          </button>
          {lastSample ? <p className="text-[11px] text-gray-500">{lastSample}</p> : null}
        </div>
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-700 text-sm text-gray-300">
          Queue (<span className="font-mono text-xs">qa:pending</span>)
        </div>
        {pending.length === 0 ? (
          <p className="p-4 text-sm text-gray-500">No pending QA cases. Run sample or close cases first.</p>
        ) : (
          <ul className="divide-y divide-surface-800">
            {pending.map((c) => (
              <li key={c.id} className="px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-sm">
                <div>
                  <Link to={`/cases/${c.id}`} className="font-mono text-brand-300 hover:underline">
                    {c.id}
                  </Link>
                  <span className="ml-2 text-gray-500">{c.status}</span>
                  {c.entity_id ? (
                    <span className="ml-2 font-mono text-xs text-gray-600">{c.entity_id}</span>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void review(c.id, String(c.status || "resolved"), String(c.status || "resolved"))}
                    className="px-2 py-1 text-xs rounded border border-emerald-600/40 text-emerald-200 hover:border-emerald-400 disabled:opacity-50"
                  >
                    Agree
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void review(c.id, String(c.status || "resolved"), "investigating")}
                    className="px-2 py-1 text-xs rounded border border-amber-600/40 text-amber-200 hover:border-amber-400 disabled:opacity-50"
                  >
                    Disagree
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
