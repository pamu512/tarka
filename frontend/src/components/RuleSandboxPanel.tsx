import { useCallback, useEffect, useMemo, useState } from "react";
import {
  decisions,
  type RuleDetail,
  type RuleReplayResponse,
  type RuleReplayRulePayload,
} from "../api/client";
import { SupportIdHint } from "./SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

function draftRulesToOverride(rules: RuleDetail[]): RuleReplayRulePayload[] {
  return rules
    .filter((r) => r.enabled !== false)
    .map((r) => ({
      id: typeof r.id === "string" && r.id.trim() ? r.id : "draft_rule",
      when: (r.when ?? []).map((c) => ({
        field: c.field,
        op: c.op ?? "eq",
        value: c.value,
      })),
      tags: [...(r.tags ?? [])],
      score_delta: typeof r.score_delta === "number" ? r.score_delta : 0,
      description: typeof r.description === "string" ? r.description : "",
    }))
    .filter((r) => r.when.length > 0);
}

function parseTraceIds(raw: string): string[] {
  return raw
    .split(/[\s,]+/g)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function RuleSandboxPanel({
  draftRules,
  defaultTenantId,
  prefilledTraceId,
}: {
  draftRules: RuleDetail[];
  defaultTenantId: string;
  /** Deep-linked from case detail (`?trace_id=`). */
  prefilledTraceId?: string | null;
}) {
  const [tenantId, setTenantId] = useState(defaultTenantId);
  const [traceIdsText, setTraceIdsText] = useState("");
  const [useRecentWindow, setUseRecentWindow] = useState(true);
  const [recentLimit, setRecentLimit] = useState(50);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<RuleReplayResponse | null>(null);

  useEffect(() => {
    setTenantId(defaultTenantId);
  }, [defaultTenantId]);

  useEffect(() => {
    if (prefilledTraceId?.trim()) {
      setTraceIdsText(prefilledTraceId.trim());
      setUseRecentWindow(false);
    }
  }, [prefilledTraceId]);

  const rulesOverride = useMemo(() => draftRulesToOverride(draftRules), [draftRules]);

  const runTest = useCallback(async () => {
    setErr(null);
    setResult(null);
    if (!rulesOverride.length) {
      setErr("Add at least one enabled rule with at least one condition to run the sandbox.");
      return;
    }
    const tid = tenantId.trim();
    if (!tid) {
      setErr("Tenant id is required.");
      return;
    }

    const traceIds = parseTraceIds(traceIdsText);
    setBusy(true);
    try {
      const payload =
        !useRecentWindow && traceIds.length > 0
          ? { tenant_id: tid, rules_override: rulesOverride, trace_ids: traceIds }
          : {
              tenant_id: tid,
              rules_override: rulesOverride,
              limit: Math.min(5000, Math.max(1, recentLimit)),
            };
      const out = await decisions.replay(payload);
      setResult(out);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Rule sandbox", action: "replay audits with draft rules" }));
    } finally {
      setBusy(false);
    }
  }, [recentLimit, rulesOverride, tenantId, traceIdsText, useRecentWindow]);

  return (
    <div id="rule-sandbox" className="bg-surface-900 border border-surface-700 rounded-xl p-5 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-300">Rule Sandbox</h3>
        <p className="text-[11px] text-gray-500 mt-1 leading-relaxed">
          Test your{" "}
          <span className="text-gray-400 font-medium">unsaved draft pack</span> against stored decision-audit
          payloads for this tenant — the same feature envelope analysts see in triage. Override evaluation uses the
          decision-api replay path (Python matcher); deploy still routes production through Rust — validate deltas before
          publishing.
        </p>
      </div>

      <label className="block text-xs text-gray-500">
        Tenant
        <input
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          className="mt-1 w-full max-w-md bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-lg px-3 py-2 font-mono"
          spellCheck={false}
        />
      </label>

      <fieldset className="space-y-2">
        <legend className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Data window</legend>
        <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
          <input
            type="radio"
            name="sandbox-scope"
            checked={useRecentWindow}
            onChange={() => setUseRecentWindow(true)}
            className="accent-brand-500"
          />
          Recent audits (triage-style window)
        </label>
        {useRecentWindow ? (
          <label className="block text-xs text-gray-500 ml-6">
            Max rows (newest first)
            <input
              type="number"
              min={1}
              max={5000}
              value={recentLimit}
              onChange={(e) => setRecentLimit(Number(e.target.value) || 50)}
              className="mt-1 w-28 bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-lg px-2 py-1"
            />
          </label>
        ) : null}

        <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
          <input
            type="radio"
            name="sandbox-scope"
            checked={!useRecentWindow}
            onChange={() => setUseRecentWindow(false)}
            className="accent-brand-500"
          />
          Specific trace IDs (e.g. current case)
        </label>
        {!useRecentWindow ? (
          <textarea
            value={traceIdsText}
            onChange={(e) => setTraceIdsText(e.target.value)}
            rows={3}
            spellCheck={false}
            placeholder="Paste UUID(s), separated by comma or newline"
            className="ml-6 w-full max-w-xl bg-surface-800 border border-surface-600 text-gray-300 text-xs font-mono rounded-lg px-3 py-2"
          />
        ) : null}
      </fieldset>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void runTest()}
          disabled={busy}
          className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {busy ? "Testing…" : "Test draft rules"}
        </button>
        <span className="text-[11px] text-gray-500">
          {rulesOverride.length} rule{rulesOverride.length === 1 ? "" : "s"} in override ·{" "}
          {draftRules.filter((r) => r.enabled === false).length > 0 ? "disabled rules skipped · " : ""}
          draft not deployed
        </span>
      </div>

      {err ? (
        <div className="rounded-lg border border-rose-500/35 bg-rose-950/30 px-3 py-2 text-sm text-rose-200 space-y-1">
          <p>{err}</p>
          <SupportIdHint
            message={err}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      ) : null}

      {result ? (
        <div className="rounded-lg border border-surface-600 bg-surface-950/50 overflow-hidden">
          <div className="px-3 py-2 border-b border-surface-700 flex flex-wrap gap-4 text-xs text-gray-400">
            <span>
              Evaluated <span className="text-gray-200 font-semibold">{result.events_evaluated}</span>
            </span>
            <span>
              Decisions changed{" "}
              <span className="text-amber-200 font-semibold">{result.decisions_changed}</span>
            </span>
            {result.missing_trace_ids.length > 0 ? (
              <span className="text-rose-300">
                Missing traces: {result.missing_trace_ids.join(", ")}
              </span>
            ) : null}
          </div>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="sticky top-0 bg-surface-900/95 border-b border-surface-700 text-gray-500 uppercase tracking-wide">
                <tr>
                  <th className="py-2 px-2 font-medium">Trace</th>
                  <th className="py-2 px-2 font-medium">Original</th>
                  <th className="py-2 px-2 font-medium">Sandbox</th>
                  <th className="py-2 px-2 font-medium">Δ</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => (
                  <tr key={row.trace_id} className="border-b border-surface-800/80 hover:bg-surface-900/80">
                    <td className="py-2 px-2 font-mono text-gray-400 align-top">{row.trace_id.slice(0, 8)}…</td>
                    <td className="py-2 px-2 align-top">
                      <span className="text-gray-300">{row.original_decision}</span>{" "}
                      <span className="text-gray-500">({row.original_score.toFixed(0)})</span>
                    </td>
                    <td className="py-2 px-2 align-top">
                      <span
                        className={
                          row.new_decision === "deny"
                            ? "text-rose-300"
                            : row.new_decision === "review"
                              ? "text-amber-200"
                              : "text-emerald-300"
                        }
                      >
                        {row.new_decision}
                      </span>{" "}
                      <span className="text-gray-500">({row.new_score.toFixed(1)})</span>
                      {row.new_rule_hits.length > 0 ? (
                        <div className="text-[10px] text-gray-500 mt-0.5 font-mono truncate max-w-[12rem]">
                          {row.new_rule_hits.join(", ")}
                        </div>
                      ) : null}
                    </td>
                    <td className="py-2 px-2 align-top">
                      {row.decision_changed ? (
                        <span className="text-amber-300 font-medium">changed</span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
