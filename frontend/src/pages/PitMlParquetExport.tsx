import { useCallback, useEffect, useMemo, useState } from "react";
import {
  pitParquetMlExport,
  type PitParquetExportRequestPayload,
  type PitParquetJobStatusResponse,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

const MS_PER_DAY = 86_400_000;
const MAX_WINDOW_MS = 366 * MS_PER_DAY;
const POLL_MS = 1000;

/** Raw ``Dispute.outcome`` values mapped by Case API ``ml_training_api`` (plus synthetic unlabeled). */
const DISPUTE_OUTCOME_OPTIONS: { value: string; label: string }[] = [
  { value: "fraud_confirmed", label: "fraud_confirmed" },
  { value: "merchant_fault", label: "merchant_fault" },
  { value: "false_positive", label: "false_positive" },
  { value: "customer_fault", label: "customer_fault" },
  { value: "inconclusive", label: "inconclusive" },
  { value: "__unlabeled__", label: "Unlabeled (no dispute string)" },
];

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

function parsePayloadKeys(raw: string): string[] | null {
  const parts = raw
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of parts) {
    if (seen.has(p)) continue;
    seen.add(p);
    out.push(p);
    if (out.length > 64) break;
  }
  return out;
}

function isTerminalJobStatus(s: string | undefined): boolean {
  return s === "SUCCEEDED" || s === "FAILED";
}

export default function PitMlParquetExport() {
  const [tenantId, setTenantId] = useState("demo");
  const [startLocal, setStartLocal] = useState(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 30);
    d.setUTCHours(0, 0, 0, 0);
    return toDatetimeLocalValue(d);
  });
  const [endLocal, setEndLocal] = useState(() => {
    const d = new Date();
    d.setUTCHours(23, 59, 0, 0);
    return toDatetimeLocalValue(d);
  });
  const [analyticsTable, setAnalyticsTable] = useState("");
  const [chunkSize, setChunkSize] = useState(10_000);
  const [featureKeysRaw, setFeatureKeysRaw] = useState("");
  const [outcomeSelection, setOutcomeSelection] = useState<Record<string, boolean>>({});

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<PitParquetJobStatusResponse | null>(null);

  const clientErrors = useMemo(() => {
    const errs: string[] = [];
    if (!tenantId.trim()) errs.push("Tenant id is required.");
    if (!/^[\w-]{1,128}$/.test(tenantId.trim())) {
      errs.push("Tenant id must be 1–128 characters (letters, digits, underscore, hyphen).");
    }
    const startIso = toUtcIsoOrNull(startLocal);
    const endIso = toUtcIsoOrNull(endLocal);
    if (!startIso) errs.push("Start date/time is invalid or empty.");
    if (!endIso) errs.push("End date/time is invalid or empty.");
    const dur = windowDurationMs(startLocal, endLocal);
    if (dur != null && dur <= 0) errs.push("End must be after start.");
    if (dur != null && dur > MAX_WINDOW_MS) {
      errs.push("Export window cannot exceed 366 days.");
    }
    if (!Number.isInteger(chunkSize) || chunkSize < 100 || chunkSize > 50_000) {
      errs.push("Chunk size must be an integer between 100 and 50,000.");
    }
    const tbl = analyticsTable.trim();
    if (tbl && !/^[a-zA-Z_][a-zA-Z0-9_]{0,127}$/.test(tbl)) {
      errs.push("Analytics table must be a single SQL identifier (letter/underscore start, then alphanumerics/underscore).");
    }
    const keys = parsePayloadKeys(featureKeysRaw);
    if (keys && keys.length > 64) errs.push("At most 64 OLAP feature keys after de-duplication.");
    return errs;
  }, [analyticsTable, chunkSize, endLocal, featureKeysRaw, outcomeSelection, startLocal, tenantId]);

  const canSubmit = clientErrors.length === 0 && !submitting;

  const refreshJob = useCallback(async (jid: string) => {
    const s = await pitParquetMlExport.getJob(jid);
    setJobStatus(s);
  }, []);

  useEffect(() => {
    if (!jobId) return;
    if (isTerminalJobStatus(jobStatus?.status)) return;

    const id = window.setInterval(() => {
      void (async () => {
        try {
          await refreshJob(jobId);
        } catch {
          /* keep last snapshot */
        }
      })();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [jobId, jobStatus?.status, refreshJob]);

  const submit = useCallback(async () => {
    if (clientErrors.length) return;
    setSubmitting(true);
    setSubmitError(null);
    setJobStatus(null);
    const startIso = toUtcIsoOrNull(startLocal)!;
    const endIso = toUtcIsoOrNull(endLocal)!;
    const keys = parsePayloadKeys(featureKeysRaw);
    const allow = DISPUTE_OUTCOME_OPTIONS.filter((o) => outcomeSelection[o.value]).map((o) => o.value);
    const body: PitParquetExportRequestPayload = {
      tenant_id: tenantId.trim(),
      window_start: startIso,
      window_end: endIso,
      chunk_size: chunkSize,
    };
    const tbl = analyticsTable.trim();
    if (tbl) body.analytics_table = tbl;
    if (keys?.length) body.payload_json_keys = keys;
    if (allow.length) body.dispute_outcome_allowlist = allow;

    try {
      const res = await pitParquetMlExport.startJob(body);
      setJobId(res.job_id);
      setJobStatus({
        job_id: res.job_id,
        status: "PENDING",
        progress_pct: 0,
        rows_written: 0,
        chunks_processed: 0,
        max_rows: 500_000,
        error: null,
        result: null,
      });
      void refreshJob(res.job_id);
    } catch (e) {
      setSubmitError(toUserFacingError(e, { subject: "PIT Parquet export", action: "start export job" }));
    } finally {
      setSubmitting(false);
    }
  }, [analyticsTable, chunkSize, clientErrors.length, endLocal, featureKeysRaw, outcomeSelection, refreshJob, startLocal, tenantId]);

  const progress = jobStatus?.progress_pct ?? 0;
  const statusLabel = jobStatus?.status ?? "—";

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-8">
      <div className="space-y-1">
        <PageTitle module="analytics">Point-in-time ML export (Parquet)</PageTitle>
        <p className="text-sm text-gray-500">
          Configure a bounded OLAP window, optional feature keys from <span className="font-mono text-xs">payload_json</span>, and
          optional Case API dispute outcomes. Exports run as background jobs on{" "}
          <span className="font-mono text-xs text-gray-400">POST /v1/ml/export/pit-parquet/jobs</span> with status from{" "}
          <span className="font-mono text-xs text-gray-400">GET /v1/ml/export/pit-parquet/jobs/{"{job_id}"}</span>.
        </p>
      </div>

      {submitError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300 space-y-1">
          <p>{submitError}</p>
          <SupportIdHint
            message={submitError}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}

      {clientErrors.length > 0 && (
        <ul className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-sm text-amber-200 list-disc list-inside space-y-1">
          {clientErrors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <form
        className="rounded-xl border border-surface-700 bg-surface-900 p-5 space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm text-gray-400">
            Tenant id
            <input
              required
              pattern="[\w-]{1,128}"
              title="1–128 characters: letters, digits, underscore, hyphen"
              className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-gray-200 font-mono text-sm"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="block text-sm text-gray-400">
            Chunk size (OLAP page rows)
            <input
              type="number"
              required
              min={100}
              max={50_000}
              step={1}
              className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-gray-200 font-mono text-sm tabular-nums"
              value={chunkSize}
              onChange={(e) => setChunkSize(Number(e.target.value))}
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm text-gray-400">
            Window start (local → UTC ISO for API)
            <input
              type="datetime-local"
              required
              className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-gray-200 text-sm"
              value={startLocal}
              onChange={(e) => setStartLocal(e.target.value)}
            />
          </label>
          <label className="block text-sm text-gray-400">
            Window end (exclusive upper bound)
            <input
              type="datetime-local"
              required
              className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-gray-200 text-sm"
              value={endLocal}
              onChange={(e) => setEndLocal(e.target.value)}
            />
          </label>
        </div>

        <label className="block text-sm text-gray-400">
          Analytics table (optional)
          <input
            pattern="[a-zA-Z_][a-zA-Z0-9_]{0,127}"
            title="Single SQL identifier, e.g. fraud_decisions"
            placeholder="Default from decision-api settings"
            className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-gray-200 font-mono text-sm"
            value={analyticsTable}
            onChange={(e) => setAnalyticsTable(e.target.value)}
            autoComplete="off"
          />
        </label>

        <label className="block text-sm text-gray-400">
          OLAP feature keys (optional, comma or whitespace separated, max 64)
          <textarea
            rows={3}
            maxLength={4000}
            placeholder="e.g. amount, channel, device_fingerprint"
            className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-gray-200 font-mono text-xs leading-relaxed"
            value={featureKeysRaw}
            onChange={(e) => setFeatureKeysRaw(e.target.value)}
          />
        </label>

        <fieldset className="border border-surface-700 rounded-lg p-4 space-y-2">
          <legend className="text-sm text-gray-400 px-1">Case API dispute outcomes (optional filter)</legend>
          <p className="text-xs text-gray-500">
            Leave all unchecked to include every outcome. When any box is checked, only rows whose joined{" "}
            <span className="font-mono">dispute_outcome</span> matches a selected value are written.{" "}
            <span className="font-mono">__unlabeled__</span> matches traces with an empty dispute outcome.
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {DISPUTE_OUTCOME_OPTIONS.map((o) => (
              <label key={o.value} className="inline-flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  className="rounded border-surface-600"
                  checked={Boolean(outcomeSelection[o.value])}
                  onChange={(e) =>
                    setOutcomeSelection((prev) => ({
                      ...prev,
                      [o.value]: e.target.checked,
                    }))
                  }
                />
                <span className="font-mono text-xs">{o.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex flex-wrap gap-3 items-center">
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:pointer-events-none text-white text-sm font-medium px-4 py-2"
          >
            {submitting ? "Starting…" : "Start Parquet export job"}
          </button>
          {jobId && (
            <span className="text-xs text-gray-500 font-mono">
              job_id: {jobId}
            </span>
          )}
        </div>
      </form>

      {jobStatus && (
        <section className="rounded-xl border border-surface-700 bg-surface-900 p-5 space-y-4" aria-live="polite">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-200">Export progress</h2>
            <span className="text-xs font-mono text-gray-500">
              status={statusLabel} · rows={jobStatus.rows_written} · chunks={jobStatus.chunks_processed} · cap=
              {jobStatus.max_rows}
            </span>
          </div>
          <div className="h-3 rounded-full bg-surface-800 overflow-hidden border border-surface-700">
            <div
              className={`h-full transition-all duration-300 ease-out rounded-full ${
                jobStatus.status === "FAILED" ? "bg-rose-500" : "bg-brand-500"
              }`}
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </div>
          <p className="text-xs text-gray-500 tabular-nums">{progress}% of configured row cap (server-side max_rows)</p>

          {jobStatus.status === "FAILED" && jobStatus.error && (
            <p className="text-sm text-rose-300 whitespace-pre-wrap">{jobStatus.error}</p>
          )}

          {jobStatus.status === "SUCCEEDED" && jobStatus.result && (
            <dl className="text-sm text-gray-300 space-y-2 border-t border-surface-700 pt-4">
              <div>
                <dt className="text-gray-500 text-xs uppercase tracking-wide">Rows</dt>
                <dd className="font-mono tabular-nums">{jobStatus.result.rows_written}</dd>
              </div>
              <div>
                <dt className="text-gray-500 text-xs uppercase tracking-wide">Artifact URI</dt>
                <dd className="font-mono text-xs break-all text-brand-300">{jobStatus.result.artifact_uri}</dd>
              </div>
              {jobStatus.result.presigned_get_url && (
                <div>
                  <dt className="text-gray-500 text-xs uppercase tracking-wide">Presigned GET</dt>
                  <dd>
                    <a
                      href={jobStatus.result.presigned_get_url}
                      className="text-brand-400 hover:text-brand-300 text-xs break-all underline"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Download
                    </a>
                  </dd>
                </div>
              )}
              {jobStatus.result.pit_note && (
                <div>
                  <dt className="text-gray-500 text-xs uppercase tracking-wide">PIT note</dt>
                  <dd className="text-gray-400 text-xs leading-relaxed">{jobStatus.result.pit_note}</dd>
                </div>
              )}
            </dl>
          )}
        </section>
      )}
    </div>
  );
}
