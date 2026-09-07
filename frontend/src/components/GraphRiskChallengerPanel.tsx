import { useState } from "react";

import { decisions } from "../api/client";
import { toUserFacingError } from "../utils/userFacingErrors";
import {
  GraphRiskChallengerStrip,
  type GraphRiskChallenger,
} from "./GraphRiskChallengerStrip";

export function GraphRiskChallengerPanel({
  tenantId,
  data,
  err,
  onRefresh,
}: {
  tenantId: string;
  data: GraphRiskChallenger | null;
  err?: string | null;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [shadowUrl, setShadowUrl] = useState("http://127.0.0.1:8091");
  const serveOk = data?.last_gate?.serve_allowed === true;

  async function run(action: "export" | "train" | "enable" | "retire") {
    setBusy(true);
    setMsg("");
    try {
      if (action === "export") await decisions.graphRiskExport(tenantId);
      if (action === "train") await decisions.graphRiskTrain(tenantId);
      if (action === "enable") await decisions.graphRiskEnableShadow(tenantId, shadowUrl);
      if (action === "retire") await decisions.graphRiskRetire(tenantId);
      setMsg(
        action === "enable"
          ? "Shadow intent saved. Set GRAPH_GNN_BETA_URL on graph-service to match. Packs still own live."
          : "Done.",
      );
      onRefresh();
    } catch (e) {
      setMsg(
        toUserFacingError(e, {
          subject: "Graph-risk challenger",
          action: action,
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3" data-testid="graph-risk-challenger-panel">
      <GraphRiskChallengerStrip data={data} err={err} />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          type="button"
          disabled={busy}
          onClick={() => void run("export")}
          className="px-2 py-1 rounded-lg bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-100"
        >
          Export labels
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void run("train")}
          className="px-2 py-1 rounded-lg bg-sky-800/80 hover:bg-sky-700 disabled:opacity-50 text-sky-50"
        >
          Train challenger
        </button>
        <input
          value={shadowUrl}
          onChange={(e) => setShadowUrl(e.target.value)}
          className="bg-surface-900 border border-surface-600 rounded px-2 py-1 text-gray-200 min-w-[14rem]"
          aria-label="Shadow overlay URL"
        />
        <button
          type="button"
          disabled={busy || !serveOk}
          title={serveOk ? "Enable shadow overlay URL" : "Disabled until serve_allowed"}
          onClick={() => void run("enable")}
          className="px-2 py-1 rounded-lg bg-emerald-900/70 hover:bg-emerald-800 disabled:opacity-50 text-emerald-50"
        >
          Enable shadow URL
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void run("retire")}
          className="px-2 py-1 rounded-lg bg-surface-800 hover:bg-surface-700 disabled:opacity-50 text-gray-300"
        >
          Retire
        </button>
      </div>
      <p className="text-[11px] text-gray-500">
        Fixed recipe only (no knobs). Enable shadow stays off unless holdout beats heuristic_v1.
        Live FLAG/REVIEW requires a Promoted pack that reads the score — not a model switch.
      </p>
      {msg ? <p className="text-xs text-gray-400">{msg}</p> : null}
    </div>
  );
}
