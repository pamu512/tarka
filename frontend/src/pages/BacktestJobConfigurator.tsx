import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  backtestJobs,
  rules,
  type BacktestJobEnqueueResponse,
  type BacktestJobRequestPayload,
  type BacktestJobStatusResponse,
  type RulePack,
} from "../api/client";
import { BacktestResultsDashboard } from "../components/BacktestResultsDashboard";
import { PageTitle } from "../components/PageTitle";
import { isTerminalBacktestStatus } from "../utils/backtestMetrics";
import { isLikelyClientTimeoutOrAbort, toUserFacingError } from "../utils/userFacingErrors";

const MS_PER_DAY = 86_400_000;
const MAX_WINDOW_MS = 90 * MS_PER_DAY;

function toDatetimeLocalValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toUtcIsoOrNull(datetimeLocal: string): string | null {
  const t = datetimeLocal.trim();
  if (!t) return null;
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

function windowDurationMs(startLocal: string, endLocal: string): number | null {
  const a = new Date(startLocal).getTime();
  const b = new Date(endLocal).getTime();
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return b - a;
}

/** Strip filesystem / UI-only keys before sending as ``rule_pack``. */
function rulePackForApi(raw: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...raw };
  delete out._file;
  for (const k of Object.keys(out)) {
    if (k.startsWith("__")) delete out[k];
  }
  return out;
}

export default function BacktestJobConfigurator() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const urlJobId = (searchParams.get("job_id") ?? "").trim();

  const [packs, setPacks] = useState<RulePack[]>([]);
  const [packsLoading, setPacksLoading] = useState(true);
  const [packsError, setPacksError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>("");

  const [tenantId, setTenantId] = useState("demo");
  const [startLocal, setStartLocal] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 14);
    d.setHours(0, 0, 0, 0);
    return toDatetimeLocalValue(d);
  });
  const [endLocal, setEndLocal] = useState(() => {
    const d = new Date();
    d.setHours(23, 59, 0, 0);
    return toDatetimeLocalValue(d);
  });
  const [chMaxSec, setChMaxSec] = useState(60);

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [lastEnqueue, setLastEnqueue] = useState<BacktestJobEnqueueResponse | null>(null);
  const [jobStatus, setJobStatus] = useState<BacktestJobStatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await rules.list();
        if (cancelled) return;
        setPacks(r.packs ?? []);
        setPacksError(null);
      } catch (e) {
        if (!cancelled) setPacksError(toUserFacingError(e, { subject: "Rule packs", action: "load the catalog" }));
      } finally {
        if (!cancelled) setPacksLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedPack = useMemo(
    () => packs.find((p) => p._file === selectedFile) ?? null,
    [packs, selectedFile],
  );

  const clientErrors = useMemo(() => {
    const errs: string[] = [];
    if (!tenantId.trim()) errs.push("Tenant id is required.");
    const startIso = toUtcIsoOrNull(startLocal);
    const endIso = toUtcIsoOrNull(endLocal);
    if (!startIso) errs.push("Start date/time is invalid or empty.");
    if (!endIso) errs.push("End date/time is invalid or empty.");
    const dur = windowDurationMs(startLocal, endLocal);
    if (dur != null && dur <= 0) errs.push("End must be after start.");
    if (dur != null && dur > MAX_WINDOW_MS) {
      errs.push("Backtest window cannot exceed 90 days (matches decision-api ``BacktestRequest`` and warehouse guardrails).");
    }
    if (!selectedFile) errs.push("Select a rule pack.");
    else if (!selectedPack?.rules?.length) errs.push("Selected pack has no rules (server rejects empty ``rule_pack.rules``).");
    if (!Number.isFinite(chMaxSec) || chMaxSec < 5 || chMaxSec > 600) {
      errs.push("ClickHouse max execution seconds must be between 5 and 600.");
    }
    return errs;
  }, [chMaxSec, endLocal, selectedFile, selectedPack, startLocal, tenantId]);

  const canSubmit = clientErrors.length === 0 && !submitting;

  const activeJobId = useMemo(() => (lastEnqueue?.job_id ?? urlJobId) || null, [lastEnqueue?.job_id, urlJobId]);

  /** Load job from ``?job_id=`` for deep links / refresh. */
  useEffect(() => {
    if (!urlJobId) return;
    let cancelled = false;
    setStatusLoading(true);
    void (async () => {
      try {
        const s = await backtestJobs.get(urlJobId);
        if (!cancelled) setJobStatus(s);
      } catch (e) {
        if (!cancelled) setSubmitError(toUserFacingError(e, { subject: "Backtest job", action: "load job from URL" }));
      } finally {
        if (!cancelled) setStatusLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [urlJobId]);

  /** Poll until terminal status when job is in flight. */
  useEffect(() => {
    const jid = activeJobId;
    if (!jid) return;
    if (isTerminalBacktestStatus(jobStatus?.status)) return;

    const id = window.setInterval(() => {
      void (async () => {
        try {
          const s = await backtestJobs.get(jid);
          setJobStatus(s);
        } catch {
          /* keep last snapshot; manual refresh still available */
        }
      })();
    }, 2500);
    return () => window.clearInterval(id);
  }, [activeJobId, jobStatus?.status]);

  const refreshJob = useCallback(async () => {
    const jid = activeJobId;
    if (!jid) return;
    setStatusLoading(true);
    try {
      const s = await backtestJobs.get(jid);
      setJobStatus(s);
    } catch (e) {
      setSubmitError(toUserFacingError(e, { subject: "Backtest job", action: "load job status" }));
    } finally {
      setStatusLoading(false);
    }
  }, [activeJobId]);

  const submit = useCallback(async () => {
    if (clientErrors.length) return;
    setSubmitting(true);
    setSubmitError(null);
    setJobStatus(null);
    const startIso = toUtcIsoOrNull(startLocal)!;
    const endIso = toUtcIsoOrNull(endLocal)!;
    const raw = selectedPack as unknown as Record<string, unknown>;
    const body: BacktestJobRequestPayload = {
      tenant_id: tenantId.trim(),
      start_time: startIso,
      end_time: endIso,
      rule_pack: rulePackForApi(raw),
      clickhouse_max_execution_seconds: Math.round(chMaxSec),
    };
    try {
      const res = await backtestJobs.enqueue(body, { timeoutMs: 55_000 });
      setLastEnqueue(res);
      setJobStatus({
        job_id: res.job_id,
        tenant_id: res.tenant_id,
        status: res.status,
        window_start: res.window_start,
        window_end: res.window_end,
        analytics_table: res.analytics_table,
        rows_processed: 0,
        rule_pack_fingerprint_sha256: res.rule_pack_fingerprint_sha256,
        metrics: null,
        error_detail: null,
        created_at: null,
        updated_at: null,
      });
      navigate(`/ops/backtest?job_id=${encodeURIComponent(res.job_id)}`, { replace: true });
    } catch (e: unknown) {
      if (isLikelyClientTimeoutOrAbort(e)) {
        setSubmitError(
          "The enqueue request timed out or was cancelled before the API responded. Backtest job submission is normally fast; check that decision-api is reachable on port 8000, proxies are healthy, then retry.",
        );
      } else {
        setSubmitError(toUserFacingError(e, { subject: "Backtest job", action: "enqueue the warehouse backtest" }));
      }
    } finally {
      setSubmitting(false);
    }
  }, [chMaxSec, clientErrors.length, endLocal, navigate, selectedPack, startLocal, tenantId]);

  return (
    <div className="max-w-6xl mx-auto px-6 py-8 text-gray-200">
      <PageTitle module="rules">Backtest job configurator</PageTitle>
      <p className="mt-2 text-sm text-gray-500">
        Submit warehouse rule backtests with the same JSON body as{" "}
        <code className="text-gray-400">POST /decisions/v1/rules/backtest/jobs</code> (<code className="text-gray-400">BacktestRequest</code> →{" "}
        <code className="text-gray-400">run_backtest_job</code>). Datetimes are sent as UTC ISO-8601; the window must not exceed 90 days when{" "}
        <code className="text-gray-400">start_time</code> is set.
      </p>

      <form
        className="mt-8 space-y-6 rounded-xl border border-surface-700 bg-surface-900/40 p-6"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">Tenant id</label>
          <input
            className="mt-1 w-full max-w-md rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-sm"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            maxLength={128}
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">Window start (local → UTC ISO)</label>
            <input
              type="datetime-local"
              className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-sm"
              value={startLocal}
              onChange={(e) => setStartLocal(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">Window end</label>
            <input
              type="datetime-local"
              className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-sm"
              value={endLocal}
              onChange={(e) => setEndLocal(e.target.value)}
              required
            />
          </div>
        </div>
        <p className="text-xs text-gray-600">
          Client guard: span ≤ 90 days. Omitting <code className="text-gray-500">start_time</code> on the API falls back to a fixed 90-day lookback from{" "}
          <code className="text-gray-500">end_time</code>; this form always sends both bounds for an explicit window.
        </p>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">Rule pack</label>
          <select
            className="mt-1 w-full max-w-xl rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-sm"
            value={selectedFile}
            onChange={(e) => setSelectedFile(e.target.value)}
            disabled={packsLoading || !!packsError}
          >
            <option value="">{packsLoading ? "Loading packs…" : "Select a pack…"}</option>
            {packs.map((p) => (
              <option key={p._file} value={p._file}>
                {p.name} ({p._file}) — {p.rules?.length ?? 0} rules
              </option>
            ))}
          </select>
          {packsError ? <p className="mt-2 text-sm text-rose-300">{packsError}</p> : null}
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">
            ClickHouse max execution seconds (5–600)
          </label>
          <input
            type="number"
            min={5}
            max={600}
            className="mt-1 w-40 rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-sm tabular-nums"
            value={chMaxSec}
            onChange={(e) => setChMaxSec(Number(e.target.value))}
          />
        </div>

        {clientErrors.length > 0 ? (
          <ul className="rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-100 list-disc pl-5 space-y-1">
            {clientErrors.map((err) => (
              <li key={err}>{err}</li>
            ))}
          </ul>
        ) : null}

        {submitError ? <p className="rounded-lg border border-rose-500/30 bg-rose-950/25 px-4 py-3 text-sm text-rose-100">{submitError}</p> : null}

        <div className="flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-brand-500 disabled:opacity-40"
          >
            {submitting ? "Submitting…" : "Enqueue backtest job"}
          </button>
          {activeJobId ? (
            <button
              type="button"
              disabled={statusLoading}
              onClick={() => void refreshJob()}
              className="rounded-xl border border-surface-600 bg-surface-800 px-5 py-2.5 text-sm font-medium text-gray-200 hover:bg-surface-700 disabled:opacity-40"
            >
              {statusLoading ? "Refreshing…" : "Refresh job status"}
            </button>
          ) : null}
        </div>
      </form>

      {lastEnqueue ? (
        <section className="mt-8 rounded-xl border border-surface-700 bg-surface-900/30 p-6 text-sm space-y-2">
          <h2 className="text-base font-semibold text-gray-200">Enqueue response</h2>
          <p>
            <span className="text-gray-500">job_id</span>{" "}
            <code className="text-brand-300">{lastEnqueue.job_id}</code>
          </p>
          <p>
            <span className="text-gray-500">window</span>{" "}
            <code className="text-gray-400">
              {lastEnqueue.window_start} → {lastEnqueue.window_end}
            </code>
          </p>
          <p>
            <span className="text-gray-500">fingerprint</span>{" "}
            <code className="text-gray-400 break-all">{lastEnqueue.rule_pack_fingerprint_sha256}</code>
          </p>
          <p className="text-gray-500">
            Wall timeout (streaming job budget): {lastEnqueue.wall_timeout_seconds}s · chunk {lastEnqueue.chunk_size} rows. A timeout marks the job{" "}
            <code className="text-gray-400">failed_timeout</code> with detail{" "}
            <code className="text-gray-400">FAILED_TIMEOUT</code> — widen the service window or shrink data if appropriate.
          </p>
        </section>
      ) : null}

      {jobStatus ? (
        <section className="mt-10 space-y-6">
          <div className="rounded-xl border border-surface-700 bg-surface-900/30 p-6 text-sm space-y-2">
            <h2 className="text-base font-semibold text-gray-200">Job status</h2>
            <p>
              <span className="text-gray-500">status</span>{" "}
              <span className="font-mono text-gray-200">{jobStatus.status}</span>
            </p>
            <p>
              <span className="text-gray-500">rows_processed</span> {jobStatus.rows_processed}
            </p>
          </div>

          <div className="rounded-xl border border-surface-700 bg-surface-900/30 p-6">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Analytics results</h2>
            <BacktestResultsDashboard job={jobStatus} />
          </div>
        </section>
      ) : null}
    </div>
  );
}
