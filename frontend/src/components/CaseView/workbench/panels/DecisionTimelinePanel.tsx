import { useCallback, useEffect, useState } from "react";
import { cases } from "../../../api/client";

export type DecisionRecord = {
  external_id: string;
  kind: string;
  category: string;
  scenario: string;
  outcome: string;
  reasoning?: string;
  created_at?: string;
  invalidated_at?: string | null;
  shadow?: boolean;
  rule_ids?: string[];
  agent_run_id?: string;
  trace_id?: string;
};

const KIND_LABEL: Record<string, string> = {
  evaluate: "Evaluate",
  agent_advise: "Agent advise",
  human_disposition: "Human disposition",
  policy_gate: "Policy gate",
};

const OUTCOME_COLOR: Record<string, string> = {
  allow: "text-emerald-400",
  deny: "text-red-400",
  review: "text-amber-400",
  escalated: "text-orange-400",
};

type WalkMode = "chain" | "impact" | null;

export function DecisionTimelinePanel({
  caseId,
  tenantId,
}: {
  caseId: string;
  tenantId: string;
}) {
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [walkMode, setWalkMode] = useState<WalkMode>(null);
  const [walkNodes, setWalkNodes] = useState<DecisionRecord[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await cases.getDecisions(caseId, tenantId);
      setDecisions(res.decisions ?? []);
      setMessage(res.message ?? null);
    } catch {
      setDecisions([]);
      setMessage("decision_graph_unreachable");
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleWalk = async (externalId: string, mode: WalkMode) => {
    if (expanded === externalId && walkMode === mode) {
      setExpanded(null);
      setWalkMode(null);
      setWalkNodes([]);
      return;
    }
    setExpanded(externalId);
    setWalkMode(mode);
    try {
      const res =
        mode === "impact"
          ? await cases.getDecisionImpact(caseId, externalId, tenantId)
          : await cases.getDecisionChain(caseId, externalId, tenantId);
      setWalkNodes((res.nodes ?? []) as DecisionRecord[]);
    } catch {
      setWalkNodes([]);
    }
  };

  if (loading) {
    return (
      <p className="text-xs text-gray-500 py-2">Loading decision graph…</p>
    );
  }

  if (decisions.length === 0) {
    return (
      <div className="rounded-lg border border-surface-700 bg-surface-900/50 p-3 mb-4">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">
          Decision accountability
        </h4>
        <p className="text-xs text-gray-500">
          {message
            ? `No decisions recorded (${message}). Enable DECISION_GRAPH_ENABLED + graph profile.`
            : "No decisions recorded for this case yet."}
        </p>
        <p className="text-[10px] text-gray-600 mt-2">
          See{" "}
          <a
            className="text-brand-400 hover:underline"
            href="https://github.com/pamu512/tarka/wiki/Decision-Accountability-Graph"
            target="_blank"
            rel="noreferrer"
          >
            decision context graph guide
          </a>
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-surface-700 bg-surface-900/50 p-3 mb-4 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          Decision accountability ({decisions.length})
        </h4>
        <button
          type="button"
          onClick={() => void load()}
          className="text-xs text-brand-400 hover:text-brand-300"
        >
          Refresh
        </button>
      </div>
      <div className="space-y-2 max-h-72 overflow-y-auto">
        {decisions.map((d) => (
          <div
            key={d.external_id}
            className="border border-surface-700 rounded-md p-2 bg-surface-800/80"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-gray-300">
                    {KIND_LABEL[d.kind] ?? d.kind}
                  </span>
                  <span
                    className={`font-semibold ${OUTCOME_COLOR[d.outcome] ?? "text-gray-300"}`}
                  >
                    {d.outcome}
                  </span>
                  {d.shadow && <span className="text-gray-500">shadow</span>}
                  {d.invalidated_at && (
                    <span className="text-red-500/80">invalidated</span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mt-0.5">{d.scenario}</p>
                {d.reasoning && (
                  <p className="text-[10px] text-gray-500 mt-0.5 line-clamp-2">
                    {d.reasoning}
                  </p>
                )}
                {(d.rule_ids?.length ?? 0) > 0 && (
                  <p className="text-[10px] text-gray-600 mt-0.5 font-mono">
                    rules: {d.rule_ids!.slice(0, 4).join(", ")}
                  </p>
                )}
                {d.created_at && (
                  <p className="text-[10px] text-gray-600 mt-0.5">
                    {new Date(d.created_at).toLocaleString()} · {d.external_id}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-1 shrink-0">
                <button
                  type="button"
                  onClick={() => void toggleWalk(d.external_id, "chain")}
                  className="text-[10px] text-brand-400"
                >
                  {expanded === d.external_id && walkMode === "chain"
                    ? "Hide chain"
                    : "Chain"}
                </button>
                <button
                  type="button"
                  onClick={() => void toggleWalk(d.external_id, "impact")}
                  className="text-[10px] text-orange-400/90"
                >
                  {expanded === d.external_id && walkMode === "impact"
                    ? "Hide impact"
                    : "Impact"}
                </button>
              </div>
            </div>
            {expanded === d.external_id && walkNodes.length > 0 && (
              <ol className="mt-2 pl-3 border-l border-surface-600 space-y-1">
                <li className="text-[10px] text-gray-600 uppercase">
                  {walkMode === "impact" ? "Downstream" : "Causal parents"}
                </li>
                {walkNodes.map((n) => (
                  <li key={n.external_id} className="text-[10px] text-gray-500">
                    {KIND_LABEL[n.kind] ?? n.kind} → {n.outcome}
                    {n.invalidated_at ? " (invalidated)" : ""}
                  </li>
                ))}
              </ol>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
