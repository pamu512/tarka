"use client";

export type KnowledgeMiniGraph = {
  nodes?: Array<{ id: string; label: string; kind?: string; subkind?: string }>;
  edges?: Array<{ from: string; to: string; rel?: string }>;
};

export type KnowledgeResolution = {
  detected_id: string;
  id_kind: string;
  found_in_graph: boolean;
  match_kind?: string | null;
  graph_backend?: string | null;
  linked_user_ids: string[];
  active_investigation_count: number;
  pending_action_conflict: boolean;
  pending_action_case_ids?: string[];
  mini_graph?: KnowledgeMiniGraph;
  /** JanusGraph / Neo4j 2-hop neighborhood (Knowledge Drop cluster). */
  two_hop_network?: Record<string, unknown> | null;
  /** DuckDB spend + spike metrics for the cluster. */
  duck_cluster_velocity?: Record<string, unknown> | null;
};

function idKindPhrase(kind: string): string {
  switch (kind) {
    case "order":
      return "This Order ID";
    case "passport":
      return "This passport ID";
    case "uuid":
    case "txn":
      return "This transaction ID";
    case "token":
      return "This ID";
    case "customer":
      return "This customer ID";
    default:
      return "This extracted ID";
  }
}

function MiniGraphSvg({ row }: { row: KnowledgeResolution }) {
  const g = row.mini_graph;
  const nodes = g?.nodes ?? [];
  const edges = g?.edges ?? [];
  if (nodes.length === 0) {
    return null;
  }
  const anchor = nodes.find((n) => n.kind === "id") ?? nodes[0];
  const others = nodes.filter((n) => n.id !== anchor?.id);
  const cx = 70;
  const cy = 44;
  const r = 36;
  const positions: Record<string, { x: number; y: number }> = {
    [anchor.id]: { x: cx, y: cy },
  };
  others.forEach((n, i) => {
    const angle = (-Math.PI / 2 + (i * 2 * Math.PI) / Math.max(others.length, 1)) % (2 * Math.PI);
    positions[n.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });

  return (
    <svg
      viewBox="0 0 140 88"
      className="h-22 w-full max-w-[11rem] text-sky-300/90"
      aria-hidden
    >
      <rect width="140" height="88" rx="8" className="fill-slate-950/80 stroke-slate-700/80" strokeWidth={1} />
      {edges.map((e) => {
        const a = positions[e.from];
        const b = positions[e.to];
        if (!a || !b) return null;
        return (
          <line
            key={`${e.from}-${e.to}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            className="stroke-slate-500"
            strokeWidth={1.25}
          />
        );
      })}
      {nodes.map((n) => {
        const p = positions[n.id];
        if (!p) return null;
        const isAnchor = n.kind === "id";
        return (
          <g key={n.id}>
            <circle
              cx={p.x}
              cy={p.y}
              r={isAnchor ? 10 : 7}
              className={
                isAnchor ? "fill-sky-600/40 stroke-sky-400/80" : "fill-slate-700/80 stroke-slate-500"
              }
              strokeWidth={1}
            />
            <text
              x={p.x}
              y={p.y + (isAnchor ? 22 : 18)}
              textAnchor="middle"
              className="font-mono text-[7px] fill-slate-400"
            >
              {(n.label || "").slice(0, 14)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function KnowledgeDropInsight({ rows }: { rows: KnowledgeResolution[] }) {
  if (!rows.length) {
    return null;
  }

  const conflict = rows.some((r) => r.pending_action_conflict);

  return (
    <div className="space-y-3 rounded-md border border-slate-800/90 bg-slate-950/50 p-3">
      {conflict ? (
        <div
          role="alert"
          className="rounded-md border border-amber-600/50 bg-amber-950/35 px-3 py-2 text-[11px] text-amber-100"
        >
          <span className="font-semibold tracking-wide text-amber-200/95">Conflict alert — </span>
          One or more extracted IDs are already tied to a lifecycle case in{" "}
          <span className="font-mono text-amber-100/90">PENDING_ACTION</span>. Resolve or merge before
          opening a duplicate investigation.
        </div>
      ) : null}

      <ul className="space-y-3">
        {rows.map((row) => {
          const phrase = idKindPhrase(row.id_kind);
          const nUsers = row.linked_user_ids?.length ?? 0;
          const nInv = row.active_investigation_count ?? 0;
          const summaryParts: string[] = [];
          if (row.found_in_graph && nUsers > 0) {
            summaryParts.push(
              `${phrase} matches the graph and is linked to ${nUsers} user account${nUsers === 1 ? "" : "s"}.`,
            );
          } else if (row.found_in_graph) {
            summaryParts.push(`${phrase} matched the graph (no user anchors on this hop).`);
          } else {
            summaryParts.push(`${phrase} was not found on the configured graph backend.`);
          }
          if (nInv > 0) {
            summaryParts.push(
              `${phrase} is linked to ${nInv} active investigation${nInv === 1 ? "" : "s"}.`,
            );
          }

          return (
            <li
              key={row.detected_id}
              className="flex flex-wrap items-start gap-3 border-b border-slate-800/60 pb-3 last:border-0 last:pb-0"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-mono text-[10px] text-slate-500">{row.detected_id}</p>
                <p className="text-[11px] leading-relaxed text-slate-300">{summaryParts.join(" ")}</p>
                {row.pending_action_conflict ? (
                  <p className="text-[10px] text-amber-300/90">
                    Pending cases: {(row.pending_action_case_ids ?? []).join(", ") || "(see lifecycle tool)"}
                  </p>
                ) : null}
              </div>
              {row.mini_graph?.nodes?.length ? (
                <div className="shrink-0 rounded border border-slate-800/80 bg-slate-900/40 p-1">
                  <MiniGraphSvg row={row} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
