import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { cases } from "../api/v1/cases";
import { decisions } from "../api/v1/decisions";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

// ── Case QA types (existing) ────────────────────────────────────

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

// ── Event QA types (new) ────────────────────────────────────────

type EventQaMetrics = {
  pending: number;
  reviewed: number;
  agree: number;
  disagree: number;
  agreement_rate: number | null;
  disagreement_rate: number | null;
  cadence_hours: number;
  sample_n: number;
};

type EventQaItem = {
  trace_id: string;
  entity_id: string;
  event_type: string;
  amount?: number | null;
  currency?: string | null;
  created_at: string | null;
};

type Tab = "cases" | "events";

export default function OpsQaDesk() {
  const { tenantId } = useTenantEnvironment();
  const [tab, setTab] = useState<Tab>("cases");

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="cases">QA sampling desk</PageTitle>
        <p className="text-sm text-gray-500">
          Two QA loops: closed-case second-review and blind evaluate-event review.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-surface-700">
        <button
          type="button"
          onClick={() => setTab("cases")}
          className={`px-4 py-2 text-sm border-b-2 transition-colors ${
            tab === "cases"
              ? "border-brand-400 text-brand-300"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Case QA
        </button>
        <button
          type="button"
          onClick={() => setTab("events")}
          className={`px-4 py-2 text-sm border-b-2 transition-colors ${
            tab === "events"
              ? "border-brand-400 text-brand-300"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Event QA (blind)
        </button>
      </div>

      {tab === "cases" ? (
        <CaseQaPanel tenantId={tenantId} />
      ) : (
        <EventQaPanel tenantId={tenantId} />
      )}
    </div>
  );
}

// ── Case QA panel (unchanged from original) ─────────────────────

function CaseQaPanel({ tenantId }: { tenantId: string }) {
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
    <>
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

      <p className="text-sm text-gray-500">
        Second-review queue from{" "}
        <span className="font-mono text-xs text-gray-400">GET /v1/cases/ops/qa-*</span> — sample
        closed cases, record agree/disagree.
      </p>

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
    </>
  );
}

// ── Event QA panel (new — blind evaluate-event review) ──────────

function EventQaPanel({ tenantId }: { tenantId: string }) {
  const [metrics, setMetrics] = useState<EventQaMetrics | null>(null);
  const [pending, setPending] = useState<EventQaItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastSample, setLastSample] = useState<string | null>(null);
  const [skipInfo, setSkipInfo] = useState<{ skip_allowed: boolean; reason: string } | null>(null);
  const [lastReview, setLastReview] = useState<{
    trace_id: string;
    agree: boolean;
    original_decision: string;
    original_score: number | null;
  } | null>(null);

  const refresh = useCallback(async () => {
    if (!tenantId.trim()) return;
    setErr(null);
    try {
      const [m, p] = await Promise.all([
        decisions.eventQaMetrics(tenantId.trim()),
        decisions.eventQaPending(tenantId.trim()),
      ]);
      setMetrics(m);
      setPending(p.items || []);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Event QA", action: "load event QA data" }));
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
      const out = await decisions.eventQaSample(tenantId.trim());
      setLastSample(`tagged ${out.tagged} / sampled ${out.sampled} (candidates ${out.candidates})`);
      await refresh();
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Event QA sample", action: "sample evaluate events" }));
    } finally {
      setBusy(false);
    }
  }

  async function checkSkip() {
    setBusy(true);
    setErr(null);
    try {
      const out = await decisions.eventQaSkipCheck(tenantId.trim());
      setSkipInfo({ skip_allowed: out.skip_allowed, reason: out.reason });
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Drift skip", action: "check drift skip" }));
    } finally {
      setBusy(false);
    }
  }

  async function submitReview(traceId: string, reviewerDecision: string) {
    setBusy(true);
    setErr(null);
    setLastReview(null);
    try {
      const out = await decisions.eventQaReview(
        { trace_id: traceId, reviewer_decision: reviewerDecision },
        tenantId.trim(),
      );
      setLastReview({
        trace_id: out.trace_id,
        agree: out.agree,
        original_decision: out.original_decision,
        original_score: out.original_score,
      });
      await refresh();
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Event QA review", action: "submit event QA verdict" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
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

      <p className="text-sm text-gray-500">
        Blind review of evaluate events from{" "}
        <span className="font-mono text-xs text-gray-400">decision_audit</span> — confirm
        whether the engine decision was correct without seeing it first.
      </p>

      {/* Metrics row */}
      <div className="grid gap-4 sm:grid-cols-5">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">Pending review</div>
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
            {busy ? "Working…" : `Sample events (N=${metrics?.sample_n ?? 20})`}
          </button>
          {lastSample ? <p className="text-[11px] text-gray-500">{lastSample}</p> : null}
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm flex flex-col justify-between gap-2">
          <button
            type="button"
            disabled={busy || !tenantId.trim()}
            onClick={() => void checkSkip()}
            className="px-3 py-2 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200 disabled:opacity-50"
          >
            {busy ? "Checking…" : "Check drift skip"}
          </button>
          {skipInfo && (
            <p className={`text-[11px] ${skipInfo.skip_allowed ? "text-emerald-400" : "text-amber-400"}`}>
              {skipInfo.skip_allowed ? "Skip allowed" : "Must sample"}: {skipInfo.reason}
            </p>
          )}
          {metrics?.cadence_hours ? (
            <p className="text-[11px] text-gray-600">Cadence: every {metrics.cadence_hours}h</p>
          ) : null}
        </div>
      </div>

      {/* Reveal after review */}
      {lastReview && (
        <div
          className={`rounded-lg border p-3 text-sm ${
            lastReview.agree
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              : "border-amber-500/30 bg-amber-500/10 text-amber-300"
          }`}
        >
          <span className="font-mono text-xs">{lastReview.trace_id.slice(0, 8)}</span>
          {" — "}
          {lastReview.agree ? "Agreed" : "Disagreed"} with engine decision:{" "}
          <span className="font-mono">{lastReview.original_decision}</span>
          {lastReview.original_score != null && (
            <span className="ml-1 font-mono text-xs opacity-75">
              (score {lastReview.original_score})
            </span>
          )}
        </div>
      )}

      {/* Pending blind review queue */}
      <div className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-700 text-sm text-gray-300">
          Blind review queue (<span className="font-mono text-xs">qa:event_pending</span>)
        </div>
        {pending.length === 0 ? (
          <p className="p-4 text-sm text-gray-500">
            No pending event reviews. Sample evaluate events to start.
          </p>
        ) : (
          <ul className="divide-y divide-surface-800">
            {pending.map((item) => (
              <li
                key={item.trace_id}
                className="px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-sm"
              >
                <div className="space-y-0.5">
                  <div>
                    <span className="font-mono text-brand-300 text-xs">
                      {item.trace_id.slice(0, 12)}…
                    </span>
                    <span className="ml-2 text-gray-500">{item.event_type}</span>
                    {item.entity_id ? (
                      <span className="ml-2 font-mono text-xs text-gray-600">{item.entity_id}</span>
                    ) : null}
                  </div>
                  <div className="text-xs text-gray-600">
                    {item.amount != null
                      ? `${item.amount} ${item.currency || ""}`
                      : ""}
                    {item.created_at ? ` · ${new Date(item.created_at).toLocaleString()}` : ""}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void submitReview(item.trace_id, "allow")}
                    className="px-2 py-1 text-xs rounded border border-emerald-600/40 text-emerald-200 hover:border-emerald-400 disabled:opacity-50"
                  >
                    Allow
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void submitReview(item.trace_id, "review")}
                    className="px-2 py-1 text-xs rounded border border-blue-600/40 text-blue-200 hover:border-blue-400 disabled:opacity-50"
                  >
                    Review
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void submitReview(item.trace_id, "deny")}
                    className="px-2 py-1 text-xs rounded border border-red-600/40 text-red-200 hover:border-red-400 disabled:opacity-50"
                  >
                    Deny
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
