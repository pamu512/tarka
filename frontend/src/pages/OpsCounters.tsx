import { useEffect, useState } from "react";
import { features } from "../api/client";
import { decisions } from "../api/v1/decisions";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const DEFAULT_EXPECTED_HINT = '{\n  "event_count_1h": 2\n}';

export default function OpsCounters() {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [gov, setGov] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [entityId, setEntityId] = useState("parity-smoke");
  const [expectedJson, setExpectedJson] = useState("");
  const [liveMsg, setLiveMsg] = useState<string | null>(null);
  const [parityMsg, setParityMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<"live" | "parity" | null>(null);

  const [fsc, setFsc] = useState<{
    schema_id?: string;
    ttl_seconds_default?: number;
    zero_fallback_on_miss?: boolean;
    offline_parity?: { job?: string; endpoint?: string };
    doc?: string;
  } | null>(null);
  const [parityStatus, setParityStatus] = useState<{
    dual_diff_proven?: boolean;
    present?: boolean;
    ok?: boolean;
    mode?: string;
    hint?: string;
    job?: string;
    generated_at?: string;
  } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [cat, g] = await Promise.all([decisions.counterCatalog(), decisions.governance()]);
        setData(cat as unknown as Record<string, unknown>);
        setGov(g as Record<string, unknown>);
      } catch (e) {
        setErr(toUserFacingError(e, { subject: "Counter catalog", action: "load counter catalog and governance" }));
      }
    })();
    void features.featureServingContract().then(setFsc).catch(() => setFsc(null));
    void decisions.counterParityStatus().then(setParityStatus).catch(() => setParityStatus(null));
  }, []);

  async function queryLiveVelocity() {
    setBusy("live");
    setLiveMsg(null);
    setErr(null);
    try {
      const out = await features.velocityQuery({
        tenant_id: tenantId,
        entity_id: entityId.trim() || "parity-smoke",
        payload: {},
      });
      setLiveMsg(JSON.stringify(out, null, 2));
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Live velocity", action: "query Redis velocity counters" }));
    } finally {
      setBusy(null);
    }
  }

  async function runParityVerify() {
    setBusy("parity");
    setParityMsg(null);
    setErr(null);
    const raw = expectedJson.trim();
    if (!raw) {
      setErr(
        "Parity verify needs expected counters JSON (e.g. event_count_1h). Query live velocity first, or paste golden expectations.",
      );
      setBusy(null);
      return;
    }
    let expected: Record<string, number>;
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("expected must be a JSON object");
      }
      expected = {};
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        const n = Number(v);
        if (!Number.isFinite(n)) {
          throw new Error(`expected.${k} must be a number`);
        }
        expected[k] = n;
      }
      if (Object.keys(expected).length === 0) {
        throw new Error("expected object has no keys");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Invalid expected JSON");
      setBusy(null);
      return;
    }
    try {
      const out = await features.parityVerify({
        tenant_id: tenantId,
        entity_id: entityId.trim() || "parity-smoke",
        expected,
        epsilon: 0.5,
      });
      setParityMsg(JSON.stringify(out, null, 2));
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Counter parity", action: "run parity verify" }));
    } finally {
      setBusy(null);
    }
  }

  const counters = (data?.counters as Array<Record<string, unknown>> | undefined) ?? [];
  const manifestVersion = String(data?.manifest_version ?? "—");
  const catalogVersion = String(data?.catalog_version ?? "—");
  const redisKeyVersion =
    data?.redis_key_version != null && String(data.redis_key_version).trim() !== ""
      ? String(data.redis_key_version)
      : "(unset — legacy AGG_KEY_VERSION)";
  const lastParity = (data?.last_parity_run as Record<string, unknown> | undefined) ?? undefined;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="compliance">Counters &amp; velocity catalog</PageTitle>
        <p className="text-sm text-gray-500">
          Declarative manifest + offline parity last-run (Wave 6 product surface)
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
      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm text-gray-300 grid gap-2 sm:grid-cols-3">
        <div>
          Manifest: <span className="font-mono text-brand-300">{manifestVersion}</span>
        </div>
        <div>
          Catalog: <span className="font-mono text-brand-300">{catalogVersion}</span>
        </div>
        <div>
          Redis key version: <span className="font-mono text-brand-300">{redisKeyVersion}</span>
        </div>
        {gov?.inference_schema_version != null ? (
          <div className="sm:col-span-3 text-xs text-gray-500">
            Inference schema:{" "}
            <span className="font-mono text-gray-400">{String(gov.inference_schema_version)}</span>
            {gov.counter_catalog && typeof gov.counter_catalog === "object" ? (
              <span className="ml-2">
                ·{" "}
                {(gov.counter_catalog as { note?: string }).note ||
                  `See ${(gov.counter_catalog as { endpoint?: string }).endpoint ?? "GET /v1/internal/counters/catalog"}`}
              </span>
            ) : null}
          </div>
        ) : null}
        {lastParity ? (
          <div className="sm:col-span-3 rounded-lg border border-surface-600 bg-surface-950/60 p-3 text-xs text-gray-400">
            Last offline parity:{" "}
            <span className={`font-mono ${lastParity.ok === false ? "text-amber-300" : "text-emerald-300"}`}>
              {lastParity.ok === false ? "FAIL" : "OK"}
            </span>
            {lastParity.generated_at != null ? (
              <span className="ml-2 font-mono text-gray-500">{String(lastParity.generated_at)}</span>
            ) : null}
            {lastParity.mode != null ? (
              <span className="ml-2">mode={String(lastParity.mode)}</span>
            ) : null}
            {lastParity.events != null ? (
              <span className="ml-2">events={String(lastParity.events)}</span>
            ) : null}
          </div>
        ) : (
          <div className="sm:col-span-3 text-xs text-gray-600">
            No <span className="font-mono">counter_parity_last.json</span> yet — CI nightly /{" "}
            <span className="font-mono">counter_replay_job.py</span> writes it for ops.
          </div>
        )}
      </div>
      {fsc ? (
        <div
          className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-xs text-gray-400 space-y-1"
          data-testid="ops-counters-feature-contract"
        >
          <div className="text-sm font-medium text-gray-300">Online / offline contract</div>
          <div className="font-mono text-gray-500">{fsc.schema_id}</div>
          <div>
            TTL {fsc.ttl_seconds_default}s · zero-fallback: {fsc.zero_fallback_on_miss ? "yes" : "no"}
          </div>
          <div>
            Parity job: <span className="font-mono text-gray-500">{fsc.offline_parity?.job}</span>
          </div>
          <div>
            Verify: <span className="font-mono text-gray-500">{fsc.offline_parity?.endpoint}</span>
          </div>
          {parityStatus ? (
            <div
              className={`mt-2 rounded-lg border px-2 py-1.5 ${
                parityStatus.dual_diff_proven
                  ? "border-emerald-500/30 text-emerald-300"
                  : "border-amber-500/30 text-amber-200"
              }`}
            >
              Dual-diff proven: {parityStatus.dual_diff_proven ? "yes" : "no"}
              {parityStatus.mode ? ` · mode=${parityStatus.mode}` : ""}
              {parityStatus.generated_at ? ` · ${parityStatus.generated_at}` : ""}
              <div className="text-[10px] text-gray-500 mt-0.5">{parityStatus.hint}</div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-300">Live velocity &amp; parity</h3>
        <p className="text-xs text-gray-500">
          Requires feature-service Redis shared with decision-api writers. Empty expected JSON is rejected — paste
          golden counters after seeding (fixture replay or evaluate).
        </p>
        <label className="block text-xs text-gray-400">
          Entity id
          <input
            className="mt-1 w-full max-w-md rounded-lg border border-surface-600 bg-surface-950 px-2 py-1.5 font-mono text-sm text-gray-200"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
          />
        </label>
        <label className="block text-xs text-gray-400">
          Expected counters JSON (optional until parity)
          <textarea
            className="mt-1 w-full max-w-xl rounded-lg border border-surface-600 bg-surface-950 px-2 py-1.5 font-mono text-[11px] text-gray-300 min-h-[72px]"
            placeholder={DEFAULT_EXPECTED_HINT}
            value={expectedJson}
            onChange={(e) => setExpectedJson(e.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void queryLiveVelocity()}
            className="px-3 py-1.5 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200 disabled:opacity-50"
          >
            {busy === "live" ? "Querying…" : "Query live velocity"}
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void runParityVerify()}
            className="px-3 py-1.5 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200 disabled:opacity-50"
          >
            {busy === "parity" ? "Running parity…" : "Run parity verify"}
          </button>
        </div>
        {liveMsg && (
          <pre className="max-h-48 overflow-auto text-[11px] text-gray-400 font-mono whitespace-pre-wrap">
            {liveMsg}
          </pre>
        )}
        {parityMsg && (
          <pre className="max-h-48 overflow-auto text-[11px] text-gray-400 font-mono whitespace-pre-wrap">
            {parityMsg}
          </pre>
        )}
      </div>
      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-800 text-left text-gray-400">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Title</th>
              <th className="px-3 py-2">Category</th>
              <th className="px-3 py-2">Window</th>
              <th className="px-3 py-2">Kind</th>
            </tr>
          </thead>
          <tbody>
            {counters.map((c) => (
              <tr key={String(c.name)} className="border-t border-surface-700/80">
                <td className="px-3 py-2 font-mono text-xs text-brand-300">{String(c.name ?? "")}</td>
                <td className="px-3 py-2 text-gray-200">{String(c.title ?? c.name ?? "")}</td>
                <td className="px-3 py-2 text-gray-400">{String(c.category ?? "—")}</td>
                <td className="px-3 py-2 text-gray-400 tabular-nums">
                  {c.window_seconds != null ? `${String(c.window_seconds)}s` : "—"}
                </td>
                <td className="px-3 py-2 text-gray-500">{String(c.kind ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">
        Offline audit → replay: <span className="font-mono">scripts/replay/run_audit_offline_parity.py</span>. Docs:{" "}
        <span className="font-mono">docs/docs/guides/counter-replay-parity.md</span>.
      </p>
    </div>
  );
}
