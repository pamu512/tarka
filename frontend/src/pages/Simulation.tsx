import { useEffect, useState, useCallback } from "react";
import { rules, simulation } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

type Tab = "simulate" | "ab-test" | "vertical-benchmark";

interface Scenario {
  name: string;
  event_count?: number;
  fraud_rate?: number;
  description?: string;
  [key: string]: unknown;
}

interface SimResult {
  total_events: number;
  fraud_rate: number;
  precision: number;
  recall: number;
  f1_score: number;
  confusion_matrix: { tp: number; fp: number; fn: number; tn: number };
  decision_distribution: Record<string, number>;
  avg_fraud_score: number;
  avg_legit_score: number;
  [key: string]: unknown;
}

interface SampleEvent {
  entity_id?: string;
  event_type?: string;
  is_fraud?: boolean;
  score?: number;
  decision?: string;
  [key: string]: unknown;
}

interface ABResult {
  set_a: SimResult;
  set_b: SimResult;
  [key: string]: unknown;
}

interface VerticalBenchmarkResult {
  scenario: string;
  vertical: string;
  baseline: SimResult;
  vertical_pack: SimResult;
  delta: Record<string, unknown>;
}

const VERTICAL_HISTORY_KEY = "tarka_vertical_benchmark_history";

export default function Simulation() {
  const [tab, setTab] = useState<Tab>("simulate");
  const [scenarios, setScenarios] = useState<Record<string, Scenario>>({});
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [customMode, setCustomMode] = useState(false);
  const [customParams, setCustomParams] = useState("{\n  \"event_count\": 500,\n  \"fraud_rate\": 0.15\n}");
  const [loading, setLoading] = useState(false);
  const [scenariosLoading, setScenariosLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [simResult, setSimResult] = useState<SimResult | null>(null);
  const [sampleEvents, setSampleEvents] = useState<SampleEvent[]>([]);

  const [ruleSetA, setRuleSetA] = useState("[\n  {\n    \"id\": \"rule-a-1\",\n    \"when\": [{\"field\": \"score\", \"op\": \"gte\", \"value\": 80}],\n    \"score_delta\": 30\n  }\n]");
  const [ruleSetB, setRuleSetB] = useState("[\n  {\n    \"id\": \"rule-b-1\",\n    \"when\": [{\"field\": \"score\", \"op\": \"gte\", \"value\": 70}],\n    \"score_delta\": 25\n  }\n]");
  const [abResult, setAbResult] = useState<ABResult | null>(null);
  const [verticalCatalog, setVerticalCatalog] = useState<Record<string, { name: string; rules: number; version: number }>>({});
  const [selectedVertical, setSelectedVertical] = useState<string>("fintech");
  const [verticalResult, setVerticalResult] = useState<VerticalBenchmarkResult | null>(null);

  const fetchScenarios = useCallback(async () => {
    try {
      const [resp, packs] = await Promise.all([
        simulation.scenarios(),
        rules.verticalPacks(),
      ]);
      setScenarios((resp.scenarios ?? resp) as Record<string, Scenario>);
      setVerticalCatalog(packs.vertical_packs ?? {});
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Simulation scenarios", action: "load scenarios" }));
    } finally {
      setScenariosLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchScenarios();
  }, [fetchScenarios]);

  async function handleRunSimulation() {
    const scenario = customMode ? "custom" : selectedScenario;
    if (!scenario) return;
    setLoading(true);
    setError(null);
    setSimResult(null);
    setSampleEvents([]);
    try {
      const options = customMode ? JSON.parse(customParams) : undefined;
      const resp = await simulation.run(scenario, options);
      const result = (resp.result ?? resp) as SimResult;
      setSimResult(result);
      const events = resp.sample_events ?? resp.sample_decisions ?? [];
      setSampleEvents((events as SampleEvent[]).slice(0, 10));
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Simulation", action: "run simulation" }));
    } finally {
      setLoading(false);
    }
  }

  async function handleRunABTest() {
    const scenario = customMode ? "custom" : selectedScenario;
    if (!scenario) return;
    setLoading(true);
    setError(null);
    setAbResult(null);
    try {
      const resp = await simulation.abTest({
        scenario,
        rule_set_a: JSON.parse(ruleSetA),
        rule_set_b: JSON.parse(ruleSetB),
      });
      setAbResult(resp as ABResult);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "A/B test", action: "run A/B test" }));
    } finally {
      setLoading(false);
    }
  }

  async function handleInstallVerticalPack(vertical: string) {
    setLoading(true);
    setError(null);
    try {
      await rules.installVerticalPack(vertical, true);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Vertical pack", action: "install selected vertical pack" }));
    } finally {
      setLoading(false);
    }
  }

  async function handleRunVerticalBenchmark() {
    const scenario = customMode ? "custom" : selectedScenario;
    if (!scenario || !selectedVertical) return;
    setLoading(true);
    setError(null);
    setVerticalResult(null);
    try {
      const resp = await simulation.benchmarkVertical({
        scenario,
        vertical: selectedVertical,
      });
      const data = resp as unknown as VerticalBenchmarkResult;
      setVerticalResult(data);
      try {
        const existingRaw = localStorage.getItem(VERTICAL_HISTORY_KEY);
        const existing = existingRaw ? (JSON.parse(existingRaw) as Array<Record<string, unknown>>) : [];
        const entry = {
          ts: new Date().toISOString(),
          scenario: data.scenario,
          vertical: data.vertical,
          baseline_f1: Number((data.baseline as Record<string, unknown>)?.f1_score ?? 0),
          vertical_f1: Number((data.vertical_pack as Record<string, unknown>)?.f1_score ?? 0),
          delta_f1: Number((data.delta ?? {})["f1_score"] ?? 0),
        };
        const next = [entry, ...existing].slice(0, 20);
        localStorage.setItem(VERTICAL_HISTORY_KEY, JSON.stringify(next));
      } catch {
        /* ignore localStorage failures */
      }
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Vertical benchmark", action: "run vertical benchmark" }));
    } finally {
      setLoading(false);
    }
  }

  if (scenariosLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-400 text-sm">Loading simulation scenarios...</p>
        </div>
      </div>
    );
  }

  const scenarioEntries = Object.entries(scenarios);

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <PageTitle module="simulation">Simulation</PageTitle>
          <p className="text-sm text-gray-500 mt-1">
            Test rule sets against synthetic fraud scenarios
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}

      {/* Tab Switcher */}
      <div className="flex gap-1 bg-surface-900 border border-surface-700 rounded-lg p-1 w-fit">
        <TabButton label="Simulate" active={tab === "simulate"} onClick={() => setTab("simulate")} />
        <TabButton label="A/B Test" active={tab === "ab-test"} onClick={() => setTab("ab-test")} />
        <TabButton label="Vertical Benchmark" active={tab === "vertical-benchmark"} onClick={() => setTab("vertical-benchmark")} />
      </div>

      {/* Scenario Selection */}
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Select Scenario</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {scenarioEntries.map(([key, s]) => (
            <button
              key={key}
              onClick={() => { setSelectedScenario(key); setCustomMode(false); }}
              className={`text-left p-4 rounded-lg border transition-colors ${
                selectedScenario === key && !customMode
                  ? "border-brand-500 bg-brand-600/10"
                  : "border-surface-700 bg-surface-800 hover:border-surface-600"
              }`}
            >
              <div className="text-sm font-medium text-gray-200">{s.name ?? key}</div>
              <div className="flex gap-3 mt-2 text-xs text-gray-400">
                {s.event_count != null && <span>{s.event_count} events</span>}
                {s.fraud_rate != null && <span>{(s.fraud_rate * 100).toFixed(0)}% fraud</span>}
              </div>
              {s.description && (
                <div className="text-xs text-gray-500 mt-2 line-clamp-2">{s.description}</div>
              )}
            </button>
          ))}

          {/* Custom option */}
          <button
            onClick={() => { setCustomMode(true); setSelectedScenario(null); }}
            className={`text-left p-4 rounded-lg border transition-colors ${
              customMode
                ? "border-brand-500 bg-brand-600/10"
                : "border-surface-700 bg-surface-800 hover:border-surface-600"
            }`}
          >
            <div className="text-sm font-medium text-gray-200">Custom</div>
            <div className="text-xs text-gray-500 mt-2">Define custom profile parameters</div>
          </button>
        </div>

        {customMode && (
          <div className="mt-4">
            <label className="text-xs text-gray-400 font-medium mb-1 block">
              Custom Parameters (JSON)
            </label>
            <textarea
              value={customParams}
              onChange={(e) => setCustomParams(e.target.value)}
              rows={5}
              className="w-full bg-surface-800 border border-surface-700 rounded-lg p-3 text-sm text-gray-200 font-mono focus:outline-none focus:border-brand-500 resize-y"
              spellCheck={false}
            />
          </div>
        )}
      </div>

      {/* Simulate Tab */}
      {tab === "simulate" && (
        <>
          <button
            onClick={handleRunSimulation}
            disabled={loading || (!selectedScenario && !customMode)}
            className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {loading && <Spinner />}
            Run Simulation
          </button>

          {simResult && <SimulationResults result={simResult} sampleEvents={sampleEvents} />}
        </>
      )}

      {/* A/B Test Tab */}
      {tab === "ab-test" && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <RuleSetEditor label="Rule Set A" value={ruleSetA} onChange={setRuleSetA} accent="text-blue-400" />
            <RuleSetEditor label="Rule Set B" value={ruleSetB} onChange={setRuleSetB} accent="text-purple-400" />
          </div>

          <button
            onClick={handleRunABTest}
            disabled={loading || (!selectedScenario && !customMode)}
            className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {loading && <Spinner />}
            Run A/B Test
          </button>

          {abResult && <ABTestResults result={abResult} />}
        </>
      )}

      {/* Vertical Benchmark Tab */}
      {tab === "vertical-benchmark" && (
        <>
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5 space-y-4">
            <h2 className="text-sm font-semibold text-gray-300">Vertical Starter Packs</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {Object.entries(verticalCatalog).map(([key, v]) => (
                <div key={key} className={`border rounded-lg p-3 ${selectedVertical === key ? "border-brand-500 bg-brand-600/10" : "border-surface-700 bg-surface-800"}`}>
                  <div className="text-sm text-gray-200 font-medium">{v.name}</div>
                  <div className="text-xs text-gray-500 mt-1">{v.rules} rules · v{v.version}</div>
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => setSelectedVertical(key)}
                      className="px-2 py-1 text-xs rounded bg-surface-700 hover:bg-surface-600 text-gray-200"
                    >
                      Select
                    </button>
                    <button
                      disabled={loading}
                      onClick={() => void handleInstallVerticalPack(key)}
                      className="px-2 py-1 text-xs rounded bg-brand-700 hover:bg-brand-600 disabled:opacity-50 text-white"
                    >
                      Install/Update
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <button
              onClick={handleRunVerticalBenchmark}
              disabled={loading || (!selectedScenario && !customMode) || !selectedVertical}
              className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
            >
              {loading && <Spinner />}
              Run Vertical Benchmark
            </button>
          </div>

          {verticalResult && (
            <div className="space-y-4">
              <ABTestResults
                result={{
                  set_a: verticalResult.baseline,
                  set_b: verticalResult.vertical_pack,
                }}
              />
              <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-gray-300 mb-3">Delta Summary</h3>
                <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap">
                  {JSON.stringify(verticalResult.delta, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── Simulation Results ──────────────────────────────────────────────── */

function SimulationResults({ result, sampleEvents }: { result: SimResult; sampleEvents: SampleEvent[] }) {
  const cm = result.confusion_matrix;
  const dist = result.decision_distribution ?? {};
  const distTotal = Object.values(dist).reduce((s, v) => s + v, 0);

  return (
    <div className="space-y-6">
      {/* Summary KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <MetricCard title="Total Events" value={String(result.total_events ?? "—")} accent="text-brand-400" />
        <MetricCard title="Fraud Rate" value={result.fraud_rate != null ? `${(result.fraud_rate * 100).toFixed(1)}%` : "—"} accent="text-red-400" />
        <MetricCard title="Precision" value={result.precision != null ? `${(result.precision * 100).toFixed(1)}%` : "—"} accent="text-cyan-400" />
        <MetricCard title="Recall" value={result.recall != null ? `${(result.recall * 100).toFixed(1)}%` : "—"} accent="text-amber-400" />
        <MetricCard title="F1 Score" value={result.f1_score != null ? result.f1_score.toFixed(3) : "—"} accent="text-green-400" />
      </div>

      {/* Confusion Matrix */}
      {cm && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Confusion Matrix</h2>
          <div className="grid grid-cols-2 gap-3 max-w-md">
            <ConfusionCell label="True Positive" value={cm.tp} color="text-red-400" bg="bg-red-500/10" />
            <ConfusionCell label="False Positive" value={cm.fp} color="text-amber-400" bg="bg-amber-500/10" />
            <ConfusionCell label="False Negative" value={cm.fn} color="text-orange-400" bg="bg-orange-500/10" />
            <ConfusionCell label="True Negative" value={cm.tn} color="text-green-400" bg="bg-green-500/10" />
          </div>
        </div>
      )}

      {/* Decision Distribution */}
      {distTotal > 0 && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Decision Distribution</h2>
          <div className="space-y-3">
            {Object.entries(dist).map(([decision, count]) => {
              const pct = distTotal > 0 ? (count / distTotal) * 100 : 0;
              return (
                <div key={decision}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-400 capitalize">{decision}</span>
                    <span className="text-xs text-gray-400">
                      {count} ({pct.toFixed(1)}%)
                    </span>
                  </div>
                  <div className="h-2.5 bg-surface-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${decisionBarColor(decision)}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Score Separation */}
      {(result.avg_fraud_score != null || result.avg_legit_score != null) && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Score Separation</h2>
          <div className="grid grid-cols-2 gap-4 max-w-md">
            <div className="text-center">
              <div className="text-xs text-gray-400 mb-1">Avg Fraud Score</div>
              <div className="text-2xl font-bold text-red-400">
                {result.avg_fraud_score?.toFixed(1) ?? "—"}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-gray-400 mb-1">Avg Legit Score</div>
              <div className="text-2xl font-bold text-green-400">
                {result.avg_legit_score?.toFixed(1) ?? "—"}
              </div>
            </div>
          </div>
          {result.avg_fraud_score != null && result.avg_legit_score != null && (
            <div className="mt-4">
              <div className="relative h-6 bg-surface-700 rounded-full overflow-hidden">
                <div
                  className="absolute top-0 left-0 h-full bg-green-500/40 rounded-l-full"
                  style={{ width: `${Math.min(result.avg_legit_score, 100)}%` }}
                />
                <div
                  className="absolute top-0 left-0 h-full bg-red-500/40 rounded-l-full"
                  style={{ width: `${Math.min(result.avg_fraud_score, 100)}%` }}
                />
                <div
                  className="absolute top-0 h-full w-0.5 bg-green-400"
                  style={{ left: `${Math.min(result.avg_legit_score, 100)}%` }}
                  title={`Legit: ${result.avg_legit_score.toFixed(1)}`}
                />
                <div
                  className="absolute top-0 h-full w-0.5 bg-red-400"
                  style={{ left: `${Math.min(result.avg_fraud_score, 100)}%` }}
                  title={`Fraud: ${result.avg_fraud_score.toFixed(1)}`}
                />
              </div>
              <div className="flex justify-between mt-1">
                <span className="text-[10px] text-green-400">Legit: {result.avg_legit_score.toFixed(1)}</span>
                <span className="text-[10px] text-red-400">Fraud: {result.avg_fraud_score.toFixed(1)}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Sample Events */}
      {sampleEvents.length > 0 && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Sample Events
            <span className="ml-2 text-xs text-gray-500 font-normal">
              (showing {sampleEvents.length})
            </span>
          </h2>
          <div className="overflow-auto max-h-[400px]">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-surface-700">
                  <th className="text-left py-2 px-2 font-medium">#</th>
                  <th className="text-left py-2 px-2 font-medium">Entity</th>
                  <th className="text-left py-2 px-2 font-medium">Type</th>
                  <th className="text-center py-2 px-2 font-medium">Fraud?</th>
                  <th className="text-center py-2 px-2 font-medium">Decision</th>
                  <th className="text-right py-2 px-2 font-medium">Score</th>
                </tr>
              </thead>
              <tbody>
                {sampleEvents.map((ev, i) => (
                  <tr key={i} className="border-b border-surface-800 hover:bg-surface-800/50">
                    <td className="py-2 px-2 text-gray-500 text-xs">{i + 1}</td>
                    <td className="py-2 px-2 text-gray-300 font-mono text-xs">
                      {truncate(ev.entity_id ?? "—", 20)}
                    </td>
                    <td className="py-2 px-2 text-gray-400 text-xs">{ev.event_type ?? "—"}</td>
                    <td className="py-2 px-2 text-center">
                      <FraudBadge isFraud={ev.is_fraud} />
                    </td>
                    <td className="py-2 px-2 text-center">
                      <DecisionBadge decision={ev.decision ?? "—"} />
                    </td>
                    <td className="py-2 px-2 text-right text-gray-300">
                      {ev.score?.toFixed(1) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── A/B Test Results ────────────────────────────────────────────────── */

function ABTestResults({ result }: { result: ABResult }) {
  const a = result.set_a;
  const b = result.set_b;
  if (!a || !b) return null;

  const metrics: { label: string; key: keyof SimResult; format: (v: number) => string; higherIsBetter: boolean }[] = [
    { label: "Precision", key: "precision", format: (v) => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
    { label: "Recall", key: "recall", format: (v) => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
    { label: "F1 Score", key: "f1_score", format: (v) => v.toFixed(3), higherIsBetter: true },
    { label: "Fraud Rate", key: "fraud_rate", format: (v) => `${(v * 100).toFixed(1)}%`, higherIsBetter: false },
    { label: "Avg Fraud Score", key: "avg_fraud_score", format: (v) => v.toFixed(1), higherIsBetter: true },
    { label: "Avg Legit Score", key: "avg_legit_score", format: (v) => v.toFixed(1), higherIsBetter: false },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">A/B Comparison</h2>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 border-b border-surface-700">
                <th className="text-left py-2 px-3 font-medium">Metric</th>
                <th className="text-right py-2 px-3 font-medium text-blue-400">Set A</th>
                <th className="text-right py-2 px-3 font-medium text-purple-400">Set B</th>
                <th className="text-right py-2 px-3 font-medium">Delta</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => {
                const valA = a[m.key] as number;
                const valB = b[m.key] as number;
                const delta = valA != null && valB != null ? valB - valA : null;
                const improved = delta != null && (m.higherIsBetter ? delta > 0 : delta < 0);
                const degraded = delta != null && (m.higherIsBetter ? delta < 0 : delta > 0);
                return (
                  <tr key={m.key} className="border-b border-surface-800 hover:bg-surface-800/50">
                    <td className="py-2.5 px-3 text-gray-300">{m.label}</td>
                    <td className="py-2.5 px-3 text-right text-gray-200 font-mono">
                      {valA != null ? m.format(valA) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-right text-gray-200 font-mono">
                      {valB != null ? m.format(valB) : "—"}
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono font-semibold ${
                      improved ? "text-green-400" : degraded ? "text-red-400" : "text-gray-500"
                    }`}>
                      {delta != null
                        ? `${delta >= 0 ? "+" : ""}${m.format(delta)}`
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Side-by-side confusion matrices */}
      {a.confusion_matrix && b.confusion_matrix && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-blue-400 mb-3">Set A — Confusion Matrix</h3>
            <div className="grid grid-cols-2 gap-3">
              <ConfusionCell label="TP" value={a.confusion_matrix.tp} color="text-red-400" bg="bg-red-500/10" />
              <ConfusionCell label="FP" value={a.confusion_matrix.fp} color="text-amber-400" bg="bg-amber-500/10" />
              <ConfusionCell label="FN" value={a.confusion_matrix.fn} color="text-orange-400" bg="bg-orange-500/10" />
              <ConfusionCell label="TN" value={a.confusion_matrix.tn} color="text-green-400" bg="bg-green-500/10" />
            </div>
          </div>
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-purple-400 mb-3">Set B — Confusion Matrix</h3>
            <div className="grid grid-cols-2 gap-3">
              <ConfusionCell label="TP" value={b.confusion_matrix.tp} color="text-red-400" bg="bg-red-500/10" />
              <ConfusionCell label="FP" value={b.confusion_matrix.fp} color="text-amber-400" bg="bg-amber-500/10" />
              <ConfusionCell label="FN" value={b.confusion_matrix.fn} color="text-orange-400" bg="bg-orange-500/10" />
              <ConfusionCell label="TN" value={b.confusion_matrix.tn} color="text-green-400" bg="bg-green-500/10" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Shared sub-components ───────────────────────────────────────────── */

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
        active
          ? "bg-brand-600 text-white"
          : "text-gray-400 hover:text-gray-200 hover:bg-surface-800"
      }`}
    >
      {label}
    </button>
  );
}

function MetricCard({ title, value, accent }: { title: string; value: string; accent: string }) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <div className="text-xs text-gray-400 font-medium mb-1">{title}</div>
      <div className={`text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function ConfusionCell({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div className={`${bg} border border-surface-700 rounded-lg p-4 text-center`}>
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  const styles: Record<string, string> = {
    allow: "bg-green-500/20 text-green-400",
    review: "bg-amber-500/20 text-amber-400",
    deny: "bg-red-500/20 text-red-400",
  };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold capitalize ${styles[decision] ?? "bg-gray-500/20 text-gray-400"}`}>
      {decision}
    </span>
  );
}

function FraudBadge({ isFraud }: { isFraud?: boolean }) {
  if (isFraud == null) return <span className="text-xs text-gray-500">—</span>;
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${
      isFraud ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"
    }`}>
      {isFraud ? "Yes" : "No"}
    </span>
  );
}

function RuleSetEditor({ label, value, onChange, accent }: { label: string; value: string; onChange: (v: string) => void; accent: string }) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <h3 className={`text-sm font-semibold ${accent} mb-3`}>{label}</h3>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={10}
        className="w-full bg-surface-800 border border-surface-700 rounded-lg p-3 text-sm text-gray-200 font-mono focus:outline-none focus:border-brand-500 resize-y"
        spellCheck={false}
      />
    </div>
  );
}

function Spinner() {
  return (
    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
  );
}

function truncate(s: string, max: number) {
  return s.length > max ? s.slice(0, max) + "\u2026" : s;
}

function decisionBarColor(decision: string): string {
  const colors: Record<string, string> = {
    allow: "bg-green-500",
    review: "bg-amber-500",
    deny: "bg-red-500",
  };
  return colors[decision] ?? "bg-gray-500";
}
