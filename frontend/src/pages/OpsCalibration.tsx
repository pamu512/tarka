import { useEffect, useState } from "react";
import { decisions } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";

export default function OpsCalibration() {
  const { tenantId } = useTenantEnvironment();
  const [profile, setProfile] = useState("default");
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [drift, setDrift] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<Array<Record<string, unknown>>>([]);
  const [err, setErr] = useState<string | null>(null);

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
        setErr(e instanceof Error ? e.message : "Failed to load calibration");
        setStatus(null);
        setDrift(null);
        setSummary([]);
      }
    })();
  }, [tenantId, profile]);

  const cal = (status?.calibration as Record<string, unknown> | undefined) ?? {};

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

      {err && <p className="text-sm text-red-400">{err}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <h3 className="text-gray-300 font-medium mb-2">Ops status</h3>
          <dl className="space-y-1 text-gray-400">
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

      <p className="text-xs text-gray-500">
        Offline reliability export: <span className="font-mono">scripts/calibration/export_reliability_dataset.py</span>.
        Pin a reference with <span className="font-mono">POST /v1/calibration/reference/{"{profile}"}</span>.
      </p>
    </div>
  );
}
