import { useEffect, useState } from "react";

import { rules, simulation } from "@/api/client";

type CatalogEntry = { name: string; rules: number; version: number; has_kill_criteria?: boolean };

type FullPack = {
  id: string;
  name: string;
  version: number;
  rules: Array<Record<string, unknown>>;
  tag_rules: Array<Record<string, unknown>>;
  kill_criteria: Record<string, unknown>;
};

/** Render one rule's `when` conditions as a compact human-readable line. */
function ruleWhenLine(rule: Record<string, unknown>): string {
  const when = rule.when as Record<string, unknown> | undefined;
  if (!when) return "(no conditions)";
  return String(when.field ?? "?") + " " + String(when.op ?? "?") + " " + String(when.value ?? "?");
}

export function VerticalPackWizard({ onInstalled }: { onInstalled: () => void }) {
  const [catalog, setCatalog] = useState<Record<string, CatalogEntry>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [full, setFull] = useState<FullPack | null>(null);
  const [loadingFull, setLoadingFull] = useState(false);
  const [benchmarks, setBenchmarks] = useState<Record<string, { precision: number; recall: number; f1_score: number }>>({});
  const [benchmarking, setBenchmarking] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    rules
      .verticalPacks()
      .then((r) => {
        if (!cancelled) setCatalog(r.vertical_packs ?? {});
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function select(key: string) {
    setSelected(key);
    setFull(null);
    setError(null);
    setDone(null);
    setLoadingFull(true);
    try {
      const pack = await rules.verticalPackDefinition(key);
      setFull(pack);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingFull(false);
    }
  }

  async function runBenchmark(key: string) {
    setBenchmarking(key);
    setError(null);
    try {
      const data = (await simulation.benchmarkVertical({
        scenario: "baseline",
        vertical: key,
      })) as { metrics?: { precision: number; recall: number; f1_score: number } };
      const m = data.metrics ?? (data as unknown as { precision: number; recall: number; f1_score: number });
      setBenchmarks((prev) => ({
        ...prev,
        [key]: { precision: m.precision, recall: m.recall, f1_score: m.f1_score },
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBenchmarking(null);
    }
  }

  async function install() {
    if (!selected) return;
    const m = benchmarks[selected];
    if (!m) return;
    setInstalling(true);
    setError(null);
    try {
      await rules.installVerticalPack(selected, {
        ...m,
        events_evaluated: 0,
      }, true);
      setDone(selected);
      onInstalled();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInstalling(false);
    }
  }

  const bm = selected ? benchmarks[selected] : undefined;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
        {Object.entries(catalog).map(([key, v]) => (
          <button
            key={key}
            onClick={() => void select(key)}
            aria-label={`Select ${v.name}`}
            className={`text-left p-3 rounded-lg border transition-colors ${
              selected === key
                ? "bg-brand-600/20 border-brand-500/50"
                : "bg-surface-800 border-surface-700 hover:bg-surface-700"
            }`}
          >
            <div className="text-sm font-medium text-gray-100">{v.name}</div>
            <div className="text-[11px] text-gray-500 mt-0.5">
              {v.rules} rules · v{v.version}
            </div>
          </button>
        ))}
        {Object.keys(catalog).length === 0 && !error && (
          <div className="text-xs text-gray-500">Loading catalog…</div>
        )}
      </div>

      {loadingFull && <div className="text-xs text-gray-500">Loading pack definition…</div>}

      {full && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-gray-200">{full.name} · rule preview</h4>
            <span className="text-[10px] text-gray-500 font-mono">
              kill criteria: {Object.keys(full.kill_criteria ?? {}).join(", ") || "none"}
            </span>
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {full.rules.map((r, i) => (
              <div key={i} className="text-[11px] font-mono text-gray-400 flex items-center gap-2">
                <span className="text-amber-400">+{String(r.score_delta ?? "?")}</span>
                <span>{ruleWhenLine(r)}</span>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3 pt-2 border-t border-surface-700">
            <button
              onClick={() => void runBenchmark(full.id)}
              disabled={benchmarking === full.id}
              className="px-3 py-1.5 text-xs rounded-lg bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white"
            >
              {benchmarking === full.id ? "Benchmarking…" : "Run benchmark"}
            </button>
            <button
              onClick={() => void install()}
              disabled={!bm || installing}
              title={bm ? "" : "Run benchmark first — install requires kill_criteria metrics."}
              className="px-3 py-1.5 text-xs rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white"
            >
              {installing ? "Installing…" : "Install pack"}
            </button>
            {!bm && <span className="text-[10px] text-gray-500">Benchmark first — install requires kill_criteria metrics.</span>}
            {bm && (
              <span className="text-[10px] text-gray-400 font-mono">
                precision {bm.precision.toFixed(2)} · recall {bm.recall.toFixed(2)} · f1 {bm.f1_score.toFixed(2)}
              </span>
            )}
          </div>
        </div>
      )}

      {done && (
        <div className="text-xs text-green-400">
          Installed {done}. It lands in Observe (shadow) — Promote from the observe panel.
        </div>
      )}
      {error && <div className="text-xs text-red-400">{error}</div>}
    </div>
  );
}
