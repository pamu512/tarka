import { useState } from "react";

import type { VisualAstPack } from "../../types/rules";

type Props = {
  open: boolean;
  onClose: () => void;
  visualPack: VisualAstPack | null;
};

const defaultFeatures = '{\n  "transaction_amount": 12000\n}';

const defaultEvaluate = `{
  "tenant_id": "demo-tenant",
  "event_type": "payment",
  "entity_id": "entity-1",
  "payload": {
    "transaction_amount": 12000
  }
}`;

export function TestRuleModal({ open, onClose, visualPack }: Props) {
  const [tab, setTab] = useState<"dry" | "evaluate">("dry");
  const [featuresJson, setFeaturesJson] = useState(defaultFeatures);
  const [evaluateJson, setEvaluateJson] = useState(defaultEvaluate);
  const [outDry, setOutDry] = useState("");
  const [outEval, setOutEval] = useState("");
  const [err, setErr] = useState("");

  if (!open) return null;

  const apiBase = (import.meta.env.VITE_DECISION_API_URL as string | undefined)?.replace(/\/$/, "") || "/api/decisions";
  const key = (import.meta.env.VITE_API_KEY as string | undefined) || "";

  const runDryRun = async () => {
    setErr("");
    setOutDry("");
    if (!visualPack) {
      setErr("Compile the canvas first (client compile must succeed).");
      return;
    }
    let features: Record<string, unknown>;
    try {
      features = JSON.parse(featuresJson) as Record<string, unknown>;
    } catch {
      setErr("Features JSON is invalid.");
      return;
    }
    try {
      const r = await fetch(`${apiBase}/v1/rules/visual/evaluate-dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(key ? { "X-Api-Key": key } : {}) },
        body: JSON.stringify({
          visual_pack: visualPack,
          features,
          redis_tags: [],
          tenant_id: "visual-builder",
          entity_id: "dry-run-entity",
        }),
      });
      const j = await r.json();
      if (!r.ok) {
        setErr(JSON.stringify(j, null, 2));
        return;
      }
      setOutDry(JSON.stringify(j, null, 2));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const runEvaluate = async () => {
    setErr("");
    setOutEval("");
    let body: unknown;
    try {
      body = JSON.parse(evaluateJson);
    } catch {
      setErr("Evaluate JSON is invalid.");
      return;
    }
    try {
      const r = await fetch(`${apiBase}/v1/decisions/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(key ? { "X-Api-Key": key } : {}) },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) {
        setErr(JSON.stringify(j, null, 2));
        return;
      }
      setOutEval(JSON.stringify(j, null, 2));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-3xl rounded-xl border border-surface-600 bg-surface-900 shadow-xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between border-b border-surface-700 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">Test rule</h2>
          <button type="button" className="text-slate-400 hover:text-white text-sm" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="flex gap-2 px-4 pt-3 border-b border-surface-800">
          <button
            type="button"
            className={`px-3 py-1.5 text-xs rounded-t ${tab === "dry" ? "bg-surface-800 text-white" : "text-slate-500"}`}
            onClick={() => setTab("dry")}
          >
            Dry-run (canvas → Rust)
          </button>
          <button
            type="button"
            className={`px-3 py-1.5 text-xs rounded-t ${tab === "evaluate" ? "bg-surface-800 text-white" : "text-slate-500"}`}
            onClick={() => setTab("evaluate")}
          >
            Full /v1/decisions/evaluate
          </button>
        </div>
        <div className="p-4 overflow-y-auto flex-1 space-y-3">
          {tab === "dry" ? (
            <>
              <p className="text-xs text-slate-500">
                Evaluates the <strong>compiled visual pack</strong> only against the feature map (same Rust path as shadow
                preview). Does not run ML/graph/OPA.
              </p>
              <textarea
                className="w-full min-h-[140px] font-mono text-xs bg-black/30 border border-surface-600 rounded p-2 text-slate-200"
                value={featuresJson}
                onChange={(e) => setFeaturesJson(e.target.value)}
              />
              <button type="button" className="px-3 py-2 rounded bg-emerald-600 text-white text-sm" onClick={() => void runDryRun()}>
                Run dry-run
              </button>
              {outDry ? (
                <pre className="text-xs bg-black/40 border border-surface-700 rounded p-2 text-emerald-200 overflow-auto max-h-56">
                  {outDry}
                </pre>
              ) : null}
            </>
          ) : (
            <>
              <p className="text-xs text-slate-500">
                POSTs a full <code className="text-slate-400">EvaluateRequest</code> to production evaluate — your canvas rule is{" "}
                <strong>not</strong> injected unless the server supports it. Use for payload sanity checks.
              </p>
              <textarea
                className="w-full min-h-[200px] font-mono text-xs bg-black/30 border border-surface-600 rounded p-2 text-slate-200"
                value={evaluateJson}
                onChange={(e) => setEvaluateJson(e.target.value)}
              />
              <button type="button" className="px-3 py-2 rounded bg-sky-600 text-white text-sm" onClick={() => void runEvaluate()}>
                POST /v1/decisions/evaluate
              </button>
              {outEval ? (
                <pre className="text-xs bg-black/40 border border-surface-700 rounded p-2 text-sky-200 overflow-auto max-h-56">
                  {outEval}
                </pre>
              ) : null}
            </>
          )}
          {err ? <pre className="text-xs text-red-300 whitespace-pre-wrap">{err}</pre> : null}
        </div>
      </div>
    </div>
  );
}
