import { useState } from "react";
import { indicativeEval } from "./indicativeEval";
import { usePackDraftStore } from "../store/packDraftStore";

export function DryRunPanel() {
  const compileForSave = usePackDraftStore((s) => s.compileForSave);
  const [payloadText, setPayloadText] = useState('{\n  "amount": 150,\n  "currency": "USD"\n}');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ hits: string[]; score: number } | null>(null);

  const run = () => {
    try {
      const payload = JSON.parse(payloadText) as Record<string, unknown>;
      setResult(indicativeEval(compileForSave(), payload));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid payload JSON");
      setResult(null);
    }
  };

  return (
    <div className="border border-surface-700 rounded-lg p-3 space-y-2 bg-surface-900/40">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm text-gray-300">Dry-run</h3>
        <span className="text-[10px] uppercase tracking-wide text-amber-400/90 border border-amber-700/40 rounded px-1.5 py-0.5">
          Indicative (not Rust)
        </span>
      </div>
      <label htmlFor="studio-dry-run-payload" className="sr-only">
        Payload JSON
      </label>
      <textarea
        id="studio-dry-run-payload"
        value={payloadText}
        onChange={(e) => setPayloadText(e.target.value)}
        rows={5}
        className="w-full font-mono text-xs bg-surface-800 border border-surface-600 text-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
      <button
        type="button"
        onClick={run}
        className="text-xs px-3 py-1.5 rounded bg-surface-700 hover:bg-surface-600 text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
      >
        Run indicative eval
      </button>
      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}
      {result && (
        <p className="text-xs text-gray-400 font-mono">
          hits=[{result.hits.join(", ")}] score={result.score}
        </p>
      )}
    </div>
  );
}
