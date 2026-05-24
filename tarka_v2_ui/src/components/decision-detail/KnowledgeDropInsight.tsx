"use client";

import type {
  DuckClusterVelocity,
  KnowledgeResolution,
  TwoHopNetwork,
} from "@/types/knowledge-drop";

export type {
  DuckClusterVelocity,
  KnowledgeMiniGraph,
  KnowledgeResolution,
  TwoHopNetwork,
} from "@/types/knowledge-drop";

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

function formatUsd(amount: number): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(amount);
}

function formatPct(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(0)}%`;
}

function spikeBadgeClass(pct: number | null): string {
  if (pct === null || !Number.isFinite(pct)) {
    return "border-slate-600/60 bg-slate-900/50 text-slate-300";
  }
  if (pct >= 200) {
    return "border-red-600/70 bg-red-950/50 text-red-100";
  }
  if (pct >= 100) {
    return "border-amber-600/60 bg-amber-950/45 text-amber-100";
  }
  if (pct >= 50) {
    return "border-orange-600/50 bg-orange-950/35 text-orange-100";
  }
  return "border-slate-600/60 bg-slate-900/50 text-slate-300";
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

function NetworkTopologySection({ network }: { network: TwoHopNetwork }) {
  if (network.error) {
    return (
      <section className="mt-2 space-y-1 rounded border border-slate-800/80 bg-slate-900/30 p-2">
        <h4 className="text-[9px] font-semibold uppercase tracking-widest text-sky-400/90">
          Network topology
        </h4>
        <p className="text-[10px] text-red-300/90">{network.error}</p>
      </section>
    );
  }

  if (!network.found && network.neighbor_node_count === 0) {
    return (
      <section className="mt-2 space-y-1 rounded border border-slate-800/80 bg-slate-900/30 p-2">
        <h4 className="text-[9px] font-semibold uppercase tracking-widest text-sky-400/90">
          Network topology
        </h4>
        <p className="text-[10px] text-slate-500">
          No 2-hop neighborhood on {network.backend || "graph"} for this anchor.
        </p>
      </section>
    );
  }

  const edgeCount =
    network.edges_summary.length > 0
      ? network.edges_summary.length
      : network.neighbor_node_count;
  const sharedIpAnomaly = network.network_ip_addresses.length > 1;
  const blockedTouch = network.blocked_device_touch_count > 0;

  return (
    <section className="mt-2 space-y-2 rounded border border-sky-900/50 bg-sky-950/20 p-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <h4 className="text-[9px] font-semibold uppercase tracking-widest text-sky-400/90">
          Network topology
        </h4>
        <span className="rounded border border-slate-700/80 bg-slate-950/60 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
          {network.backend}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10px]">
        <div>
          <dt className="text-slate-500">Connected nodes</dt>
          <dd className="font-mono text-slate-200">{network.neighbor_node_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Edge summaries</dt>
          <dd className="font-mono text-slate-200">{edgeCount}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Users</dt>
          <dd className="font-mono text-slate-200">{network.network_user_ids.length}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Devices / IPs</dt>
          <dd className="font-mono text-slate-200">
            {network.network_device_ids.length} / {network.network_ip_addresses.length}
          </dd>
        </div>
      </dl>

      {(blockedTouch || sharedIpAnomaly) && (
        <ul className="flex flex-wrap gap-1.5">
          {blockedTouch ? (
            <li
              className="rounded border border-red-600/70 bg-red-950/45 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-red-100"
            >
              Blocked device touch ×{network.blocked_device_touch_count}
            </li>
          ) : null}
          {sharedIpAnomaly ? (
            <li
              className="rounded border border-amber-600/60 bg-amber-950/40 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-100"
            >
              Shared IP cluster ({network.network_ip_addresses.length})
            </li>
          ) : null}
        </ul>
      )}

      {network.edges_summary.length > 0 ? (
        <ul className="max-h-24 space-y-0.5 overflow-y-auto font-mono text-[9px] text-slate-400">
          {network.edges_summary.slice(0, 8).map((edge, i) => (
            <li key={`${edge}-${i}`} className="truncate">
              {edge}
            </li>
          ))}
        </ul>
      ) : (
        <ul className="space-y-1 text-[10px] text-slate-400">
          {network.network_user_ids.slice(0, 4).map((uid) => (
            <li key={`u-${uid}`} className="truncate font-mono">
              user {uid}
            </li>
          ))}
          {network.network_device_ids.slice(0, 3).map((did) => (
            <li key={`d-${did}`} className="truncate font-mono">
              device {did}
            </li>
          ))}
          {network.network_ip_addresses.slice(0, 3).map((ip) => (
            <li key={`ip-${ip}`} className="truncate font-mono">
              ip {ip}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ClusterVelocitySection({ velocity }: { velocity: DuckClusterVelocity }) {
  if (velocity.error) {
    return (
      <section className="mt-2 space-y-1 rounded border border-slate-800/80 bg-slate-900/30 p-2">
        <h4 className="text-[9px] font-semibold uppercase tracking-widest text-violet-400/90">
          Cluster velocity
        </h4>
        <p className="text-[10px] text-red-300/90">{velocity.error}</p>
      </section>
    );
  }

  const spike = velocity.spike_pct_vs_flat_baseline_2h;
  const hasSpike = spike !== null && Number.isFinite(spike) && spike >= 50;
  const peakMinute = [...velocity.minute_velocity_last_48h]
    .filter((r) => typeof r.spend === "number" && Number.isFinite(r.spend))
    .sort((a, b) => (b.spend ?? 0) - (a.spend ?? 0))[0];

  return (
    <section className="mt-2 space-y-2 rounded border border-violet-900/45 bg-violet-950/15 p-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <h4 className="text-[9px] font-semibold uppercase tracking-widest text-violet-400/90">
          Cluster velocity
        </h4>
        <span className="rounded border border-slate-700/80 bg-slate-950/60 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
          {velocity.window_days}d window
        </span>
        {spike !== null && Number.isFinite(spike) ? (
          <span
            className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${spikeBadgeClass(spike)}`}
          >
            2h spike {formatPct(spike)}
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10px]">
        <div>
          <dt className="text-slate-500">Spend (window)</dt>
          <dd className="font-mono text-slate-200">{formatUsd(velocity.total_spend_window)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Txns</dt>
          <dd className="font-mono text-slate-200">{velocity.txn_count_window}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Spend last 2h</dt>
          <dd className={`font-mono ${hasSpike ? "text-amber-200" : "text-slate-200"}`}>
            {formatUsd(velocity.spend_last_2h)}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Prior window</dt>
          <dd className="font-mono text-slate-200">{formatUsd(velocity.spend_excluding_last_2h)}</dd>
        </div>
      </dl>

      {hasSpike ? (
        <p className="text-[10px] leading-snug text-amber-100/90">
          Last 2h spend is elevated vs the flat baseline for the remainder of the {velocity.window_days}
          -day cluster window — review for coordinated burst activity.
        </p>
      ) : null}

      {peakMinute && typeof peakMinute.spend === "number" ? (
        <p className="text-[10px] text-slate-500">
          Peak minute (48h):{" "}
          <span className="font-mono text-slate-300">{formatUsd(peakMinute.spend)}</span>
          {peakMinute.minute_bucket ? (
            <>
              {" "}
              at <span className="font-mono text-slate-400">{peakMinute.minute_bucket}</span>
            </>
          ) : null}
        </p>
      ) : null}
    </section>
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

          const showTopology = row.two_hop_network != null;
          const showVelocity = row.duck_cluster_velocity != null;
          const showGraphColumn =
            Boolean(row.mini_graph?.nodes?.length) || showTopology || showVelocity;

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
              {showGraphColumn ? (
                <div className="w-full min-w-[11rem] max-w-[14rem] shrink-0 space-y-0 sm:w-auto">
                  {row.mini_graph?.nodes?.length ? (
                    <div className="rounded border border-slate-800/80 bg-slate-900/40 p-1">
                      <MiniGraphSvg row={row} />
                    </div>
                  ) : null}
                  {showTopology && row.two_hop_network ? (
                    <NetworkTopologySection network={row.two_hop_network} />
                  ) : null}
                  {showVelocity && row.duck_cluster_velocity ? (
                    <ClusterVelocitySection velocity={row.duck_cluster_velocity} />
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
