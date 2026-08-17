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
  const [chain, setChain] = useState<{ nodes: DecisionRecord[] } | null>(null);
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

  const toggleChain = async (externalId: string) => {
    if (expanded === externalId) {
      setExpanded(null);
      setChain(null);
      return;
    }
    setExpanded(externalId);
    try {
      const res = await cases.getDecisionChain(caseId, externalId, tenantId);
      setChain({ nodes: (res.nodes ?? []) as DecisionRecord[] });
    } catch {
      setChain(null);
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
            ? `No decisions recorded (${message}). Enable DECISION_GRAPH_ENABLED on graph-service.`
            : "No decisions recorded for this case yet."}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-surface-700 bg-surface-900/50 p-3 mb-4 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          Decision accountability
        </h4>
        <button
          type="button"
          onClick={() => void load()}
          className="text-xs text-brand-400 hover:text-brand-300"
        >
          Refresh
        </button>
      </div>
      <div className="space-y-2 max-h-64 overflow-y-auto">
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
                  {d.shadow && (
                    <span className="text-gray-500">shadow</span>
                  )}
                  {d.invalidated_at && (
                    <span className="text-red-500/80">invalidated</span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mt-0.5 truncate">{d.scenario}</p>
                {d.created_at && (
                  <p className="text-[10px] text-gray-600 mt-0.5">
                    {new Date(d.created_at).toLocaleString()}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => void toggleChain(d.external_id)}
                className="text-[10px] text-brand-400 shrink-0"
              >
                {expanded === d.external_id ? "Hide chain" : "Chain"}
              </button>
            </div>
            {expanded === d.external_id && chain && (
              <ol className="mt-2 pl-3 border-l border-surface-600 space-y-1">
                {chain.nodes.map((n) => (
                  <li key={n.external_id} className="text-[10px] text-gray-500">
                    {KIND_LABEL[n.kind] ?? n.kind} → {n.outcome}
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
