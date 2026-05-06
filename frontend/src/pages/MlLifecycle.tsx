import { useEffect, useState } from "react";
import { ml, type ModelInfo } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

type VerStat = {
  version: number;
  active?: boolean;
  traffic_weight?: number;
  total_inferences?: number;
  avg_latency_ms?: number;
  last_used?: number;
};

export default function MlLifecycle() {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [stats, setStats] = useState<VerStat[]>([]);
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null);
  const [approveVer, setApproveVer] = useState("");
  const [actor, setActor] = useState(() =>
    typeof localStorage !== "undefined" ? localStorage.getItem("tarka.ml_actor") || "" : "",
  );
  const [trafficJson, setTrafficJson] = useState('{"1": 100}');
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [h, m] = await Promise.all([ml.health(), ml.models()]);
        setHealth(h as Record<string, unknown>);
        setModels(m.models);
        if (m.models.length && !selected) {
          setSelected(m.models[0]!.model_name);
        }
      } catch (e) {
        setErr(toUserFacingError(e, { subject: "ML lifecycle", action: "load ML health and model registry" }));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only bootstrap for ML models
  }, []);

  useEffect(() => {
    if (!selected) {
      setStats([]);
      return;
    }
    (async () => {
      try {
        const s = await ml.modelStats(selected);
        setStats((s.versions as VerStat[]) ?? []);
        setLineage(null);
      } catch {
        setStats([]);
      }
    })();
  }, [selected]);

  const persistActor = (v: string) => {
    setActor(v);
    if (typeof localStorage !== "undefined") localStorage.setItem("tarka.ml_actor", v);
  };

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    setErr(null);
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "ML lifecycle action", action: "run selected ML lifecycle action" }));
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="analytics">ML lifecycle</PageTitle>
        <p className="text-sm text-gray-500">
          Registry, approval, activation, traffic split, rollback, and lineage — same surface as{" "}
          <span className="font-mono text-xs text-gray-400">ml-scoring /v1/models/*</span>.
        </p>
      </div>

      {health && (
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm text-gray-300 flex flex-wrap gap-4">
          <span>
            Status: <span className="text-emerald-400 font-medium">{String(health.status)}</span>
          </span>
          <span>
            Env model: <span className="font-mono text-brand-300">{String(health.model_version ?? "—")}</span>
          </span>
          <span>ONNX session: {health.onnx_loaded ? "yes" : "no"}</span>
          <span>
            Registry: <span className="tabular-nums">{String(health.registry_models ?? 0)}</span> versions
          </span>
        </div>
      )}

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
      {msg && <p className="text-sm text-emerald-400">{msg}</p>}

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-4">
        <div className="flex flex-wrap gap-3 items-end">
          <label className="text-sm text-gray-400">
            Model
            <select
              className="ml-2 mt-1 block rounded-lg border border-surface-600 bg-surface-950 px-2 py-1 text-gray-200"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.model_name} value={m.model_name}>
                  {m.model_name} v{m.version} {m.active ? "(active)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-gray-400">
            Actor (for approve)
            <input
              className="ml-2 mt-1 block rounded-lg border border-surface-600 bg-surface-950 px-2 py-1 text-gray-200 font-mono text-sm min-w-[12rem]"
              value={actor}
              onChange={(e) => persistActor(e.target.value)}
              placeholder="risk-ops@example.com"
            />
          </label>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500 border-b border-surface-700">
              <tr>
                <th className="py-2 pr-3">Ver</th>
                <th className="py-2 pr-3">Weight</th>
                <th className="py-2 pr-3">Inferences</th>
                <th className="py-2 pr-3">Avg ms</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((v) => (
                <tr key={v.version} className="border-t border-surface-800">
                  <td className="py-2 pr-3 font-mono text-brand-300">
                    {v.version}
                    {v.active ? <span className="ml-2 text-emerald-500 text-xs">active</span> : null}
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{v.traffic_weight ?? "—"}</td>
                  <td className="py-2 pr-3 tabular-nums">{v.total_inferences ?? 0}</td>
                  <td className="py-2 pr-3 tabular-nums">{v.avg_latency_ms ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap gap-2 border-t border-surface-800 pt-4">
          <div className="flex gap-2 items-center">
            <input
              className="w-16 rounded border border-surface-600 bg-surface-950 px-2 py-1 text-sm font-mono"
              placeholder="ver"
              value={approveVer}
              onChange={(e) => setApproveVer(e.target.value)}
            />
            <button
              type="button"
              className="px-3 py-1.5 rounded-lg bg-surface-700 text-sm text-gray-200 hover:bg-surface-600"
              onClick={() => {
                const v = parseInt(approveVer, 10);
                if (!selected || !actor.trim() || Number.isNaN(v)) {
                  setErr("Pick a model, version, and actor");
                  return;
                }
                run(() => ml.approve(selected, v, actor.trim()), `Approved v${v}`);
              }}
            >
              Approve
            </button>
            <button
              type="button"
              className="px-3 py-1.5 rounded-lg bg-brand-600/30 text-sm text-brand-200 hover:bg-brand-600/40"
              onClick={() => {
                const v = parseInt(approveVer, 10);
                if (!selected || Number.isNaN(v)) {
                  setErr("Pick a model and version");
                  return;
                }
                run(() => ml.activate(selected, v), `Activated v${v}`);
              }}
            >
              Activate
            </button>
          </div>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg bg-surface-700 text-sm text-gray-200 hover:bg-surface-600"
            onClick={() => run(() => ml.rollback(selected), "Rolled back")}
          >
            Rollback
          </button>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg bg-surface-700 text-sm text-gray-200 hover:bg-surface-600"
            onClick={() => {
              let w: Record<number, number>;
              try {
                w = JSON.parse(trafficJson) as Record<number, number>;
              } catch {
                setErr("Invalid JSON for weights");
                return;
              }
              run(() => ml.setTrafficSplit(selected, w), "Traffic split updated");
            }}
          >
            Apply traffic JSON
          </button>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg bg-surface-700 text-sm text-gray-200 hover:bg-surface-600"
            onClick={() => {
              const v = parseInt(approveVer, 10);
              if (!selected || Number.isNaN(v)) {
                setErr("Pick a model and version for lineage");
                return;
              }
              (async () => {
                setErr(null);
                setMsg(null);
                try {
                  const r = await ml.modelLineage(selected, v);
                  setLineage(r.lineage as Record<string, unknown>);
                  setMsg("Lineage loaded");
                } catch (e) {
                  setErr(toUserFacingError(e, { subject: "Model lineage", action: "load model lineage" }));
                }
              })();
            }}
          >
            Lineage
          </button>
        </div>
        <label className="block text-xs text-gray-500">
          Traffic weights (sum 100):{" "}
          <input
            className="mt-1 w-full max-w-md font-mono rounded border border-surface-600 bg-surface-950 px-2 py-1 text-gray-300 text-sm"
            value={trafficJson}
            onChange={(e) => setTrafficJson(e.target.value)}
          />
        </label>
      </div>

      {lineage && (
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <h3 className="text-gray-300 font-medium mb-2">Lineage</h3>
          <div className="font-mono text-xs text-brand-300 break-all">{String(lineage.sha256 ?? "")}</div>
          <pre className="mt-2 max-h-64 overflow-auto text-xs text-gray-500 bg-surface-950 p-2 rounded-lg">
            {JSON.stringify(lineage.signed_payload ?? lineage, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
