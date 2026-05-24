export type KnowledgeMiniGraph = {
  nodes?: Array<{ id: string; label: string; kind?: string; subkind?: string }>;
  edges?: Array<{ from: string; to: string; rel?: string }>;
};

/** JanusGraph / Neo4j 2-hop neighborhood from orchestrator ``two_hop_neighbor_network``. */
export type TwoHopNetwork = {
  found: boolean;
  anchor_user_id: string;
  backend: string;
  neighbor_node_count: number;
  blocked_device_touch_count: number;
  network_user_ids: string[];
  network_transaction_ids: string[];
  network_device_ids: string[];
  network_ip_addresses: string[];
  edges_summary: string[];
  error?: string;
};

/** DuckDB cluster spend + velocity from ``cluster_spend_velocity_for_network``. */
export type DuckClusterVelocity = {
  window_days: number;
  total_spend_window: number;
  txn_count_window: number;
  spend_last_2h: number;
  spend_excluding_last_2h: number;
  spike_pct_vs_flat_baseline_2h: number | null;
  minute_velocity_last_48h: Array<{ minute_bucket?: string; spend?: number }>;
  error?: string;
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
  two_hop_network?: TwoHopNetwork | null;
  duck_cluster_velocity?: DuckClusterVelocity | null;
};

function asStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((x): x is string => typeof x === "string" && x.trim().length > 0);
}

function asNumber(raw: unknown, fallback = 0): number {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

export function normalizeTwoHopNetwork(raw: unknown): TwoHopNetwork | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.error === "string" && o.error.trim()) {
    return {
      found: false,
      anchor_user_id: typeof o.anchor_user_id === "string" ? o.anchor_user_id : "",
      backend: typeof o.backend === "string" ? o.backend : "error",
      neighbor_node_count: 0,
      blocked_device_touch_count: 0,
      network_user_ids: [],
      network_transaction_ids: [],
      network_device_ids: [],
      network_ip_addresses: [],
      edges_summary: [],
      error: o.error.trim(),
    };
  }
  const edgesRaw = o.edges_summary;
  let edges_summary: string[] = [];
  if (Array.isArray(edgesRaw)) {
    edges_summary = edgesRaw
      .map((e) => {
        if (typeof e === "string") return e.trim();
        if (e && typeof e === "object") {
          const er = e as Record<string, unknown>;
          const rel = typeof er.rel === "string" ? er.rel : "edge";
          const from = typeof er.from === "string" ? er.from : "?";
          const to = typeof er.to === "string" ? er.to : "?";
          return `${from} → ${to} (${rel})`;
        }
        return "";
      })
      .filter(Boolean);
  }
  return {
    found: Boolean(o.found),
    anchor_user_id: typeof o.anchor_user_id === "string" ? o.anchor_user_id : "",
    backend: typeof o.backend === "string" ? o.backend : "unknown",
    neighbor_node_count: asNumber(o.neighbor_node_count),
    blocked_device_touch_count: asNumber(o.blocked_device_touch_count),
    network_user_ids: asStringArray(o.network_user_ids),
    network_transaction_ids: asStringArray(o.network_transaction_ids),
    network_device_ids: asStringArray(o.network_device_ids),
    network_ip_addresses: asStringArray(o.network_ip_addresses),
    edges_summary,
  };
}

export function normalizeDuckClusterVelocity(raw: unknown): DuckClusterVelocity | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.error === "string" && o.error.trim()) {
    return {
      window_days: 30,
      total_spend_window: 0,
      txn_count_window: 0,
      spend_last_2h: 0,
      spend_excluding_last_2h: 0,
      spike_pct_vs_flat_baseline_2h: null,
      minute_velocity_last_48h: [],
      error: o.error.trim(),
    };
  }
  const spikeRaw = o.spike_pct_vs_flat_baseline_2h;
  const spike =
    spikeRaw === null || spikeRaw === undefined
      ? null
      : asNumber(spikeRaw, NaN);
  const minute_velocity_last_48h: DuckClusterVelocity["minute_velocity_last_48h"] = [];
  if (Array.isArray(o.minute_velocity_last_48h)) {
    for (const row of o.minute_velocity_last_48h) {
      if (!row || typeof row !== "object") continue;
      const r = row as Record<string, unknown>;
      minute_velocity_last_48h.push({
        minute_bucket: typeof r.minute_bucket === "string" ? r.minute_bucket : undefined,
        spend: asNumber(r.spend, NaN),
      });
    }
  }
  return {
    window_days: Math.max(1, asNumber(o.window_days, 30)),
    total_spend_window: asNumber(o.total_spend_window),
    txn_count_window: asNumber(o.txn_count_window),
    spend_last_2h: asNumber(o.spend_last_2h),
    spend_excluding_last_2h: asNumber(o.spend_excluding_last_2h),
    spike_pct_vs_flat_baseline_2h: spike !== null && Number.isFinite(spike) ? spike : null,
    minute_velocity_last_48h,
  };
}

export function normalizeKnowledgeResolution(raw: unknown): KnowledgeResolution | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.detected_id !== "string") return null;
  return {
    detected_id: o.detected_id,
    id_kind: typeof o.id_kind === "string" ? o.id_kind : "unknown",
    found_in_graph: Boolean(o.found_in_graph),
    match_kind: typeof o.match_kind === "string" ? o.match_kind : null,
    graph_backend: typeof o.graph_backend === "string" ? o.graph_backend : null,
    linked_user_ids: asStringArray(o.linked_user_ids),
    active_investigation_count: asNumber(o.active_investigation_count),
    pending_action_conflict: Boolean(o.pending_action_conflict),
    pending_action_case_ids: asStringArray(o.pending_action_case_ids),
    mini_graph:
      o.mini_graph && typeof o.mini_graph === "object"
        ? (o.mini_graph as KnowledgeMiniGraph)
        : undefined,
    two_hop_network: normalizeTwoHopNetwork(o.two_hop_network),
    duck_cluster_velocity: normalizeDuckClusterVelocity(o.duck_cluster_velocity),
  };
}

export function normalizeKnowledgeRows(raw: unknown): KnowledgeResolution[] {
  if (!Array.isArray(raw)) return [];
  const out: KnowledgeResolution[] = [];
  for (const item of raw) {
    const row = normalizeKnowledgeResolution(item);
    if (row) out.push(row);
  }
  return out;
}
