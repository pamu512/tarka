import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  graph,
  type CommunityResult,
  type FraudRingResult,
  type GraphEdge,
  type GraphNode,
  type GraphPathExplanation,
} from "../api/client";
import { GraphContextPanel } from "../components/GraphContextPanel";
import { LinkAnalysisForceGraph } from "../components/LinkAnalysisForceGraph";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useFailoverPlanes } from "../context/FailoverPlaneContext";
import {
  filterWorkspaceNodes,
  parseGraphWorkspaceParams,
  storedDisplayRisk,
  typeHistogram,
  mergeSubgraphs,
  type WorkspaceFilter,
} from "../domain/graphInvestigation";
import {
  LINK_ANALYSIS_MAX_NODES,
  type LinkAnalysisGraphNode,
  toForceGraphLinks,
} from "../domain/linkAnalysisGraph";
import { pruneSubgraphAsync } from "../domain/linkAnalysisPruneWorkerRunner";
import { toUserFacingError } from "../utils/userFacingErrors";

const NODE_COLORS: Record<string, string> = {
  Person: "#3b82f6",
  Account: "#22c55e",
  Device: "#f97316",
  Payment: "#a855f7",
  Email: "#06b6d4",
  IP: "#ec4899",
  Address: "#84cc16",
};

const FALLBACK_SCHEMA_TYPES = ["Person", "Account", "Device", "Payment", "Email", "IP", "Address"];

const EMPTY_FILTER: WorkspaceFilter = {
  types: null,
  minRisk: null,
  scoredOnly: false,
  growthOnly: false,
};

function defaultTenantId(): string {
  try {
    const t = localStorage.getItem("tarka.tenant_id");
    if (t && t.trim()) return t.trim();
  } catch {
    /* ignore */
  }
  return "demo";
}

function paintStoredRisk(nodes: GraphNode[]): LinkAnalysisGraphNode[] {
  const stored = new Map(nodes.map((n) => [n.id, storedDisplayRisk(n)]));
  return nodes.map((n) => ({ ...n, displayRisk: stored.get(n.id) ?? null }));
}

function pathNodeIds(expl: GraphPathExplanation, seedId: string, selectedId: string): Set<string> {
  const ids = new Set<string>([seedId, selectedId]);
  if (expl.subject) ids.add(expl.subject);
  if (expl.target) ids.add(expl.target);
  for (const p of expl.paths) {
    if (p.entity_id) ids.add(p.entity_id);
    if (p.target_entity_id) ids.add(p.target_entity_id);
    for (const hop of p.hops ?? []) {
      if (hop.entity_id) ids.add(hop.entity_id);
    }
  }
  return ids;
}

function pruneBanner(originalNodeCount: number, prunedNodeCount: number, rawNodeCount: number): string {
  return (
    `Performance cap: subgraph had ${originalNodeCount.toLocaleString()} entities; ` +
    `showing ${prunedNodeCount.toLocaleString()} (seed + highest-degree neighbors).` +
    (rawNodeCount > LINK_ANALYSIS_MAX_NODES
      ? " Pruning ran in a background worker so the main thread stayed responsive."
      : "")
  );
}

const inputClass =
  "bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50";
const chipClass = (on: boolean) =>
  `px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
    on
      ? "bg-brand-600/30 text-brand-200 border-brand-500/50"
      : "bg-surface-800 text-gray-400 border-surface-600 hover:text-gray-200"
  }`;

export default function GraphInvestigationPage() {
  const { graphPlaneDisabled } = useFailoverPlanes();
  const [params, setParams] = useSearchParams();
  const parsed = useMemo(
    () => parseGraphWorkspaceParams(params, defaultTenantId()),
    [params],
  );
  const entityId = parsed.entityId.trim();
  const tenantId = parsed.tenantId.trim() || defaultTenantId();
  const depth = parsed.depth;

  const [searchQ, setSearchQ] = useState("");
  const [searchLabel, setSearchLabel] = useState<string | null>(null);
  const [searchHits, setSearchHits] = useState<
    Array<{ entity_id: string; tenant_id: string; labels: string[]; scored: boolean; risk_score: number | null }>
  >([]);
  const [searchErr, setSearchErr] = useState("");
  const [schemaTypes, setSchemaTypes] = useState<string[]>(FALLBACK_SCHEMA_TYPES);

  const [topN, setTopN] = useState<Array<{ entity_id: string; labels: string[]; risk_score: number }>>([]);
  const [topNErr, setTopNErr] = useState("");

  const [loaded, setLoaded] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanding, setExpanding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pruneNote, setPruneNote] = useState("");

  const [filter, setFilter] = useState<WorkspaceFilter>(EMPTY_FILTER);
  const [minRiskText, setMinRiskText] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [dossierMessage, setDossierMessage] = useState<string | null>(null);
  const [highlightIds, setHighlightIds] = useState<Set<string> | undefined>(undefined);

  const [communities, setCommunities] = useState<CommunityResult[]>([]);
  const [fraudRings, setFraudRings] = useState<FraudRingResult[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [tenantDraft, setTenantDraft] = useState(tenantId);
  const loadedRef = useRef(loaded);
  loadedRef.current = loaded;
  const loadingRef = useRef(loading);
  loadingRef.current = loading;
  const seedLoadGenRef = useRef(0);

  useEffect(() => {
    setTenantDraft(tenantId);
  }, [tenantId]);

  const writeUrl = useCallback(
    (next: { entityId: string; tenantId: string; depth: number }) => {
      const sp = new URLSearchParams();
      if (next.entityId) sp.set("entity_id", next.entityId);
      if (next.tenantId) sp.set("tenant_id", next.tenantId);
      sp.set("depth", String(next.depth));
      setParams(sp, { replace: true });
    },
    [setParams],
  );

  const selectEntity = useCallback(
    (id: string, tid = tenantId) => {
      writeUrl({ entityId: id, tenantId: tid, depth });
      setSearchQ("");
      setSearchHits([]);
    },
    [depth, tenantId, writeUrl],
  );

  useEffect(() => {
    if (graphPlaneDisabled) return;
    let cancelled = false;
    void (async () => {
      try {
        const s = await graph.schema(tenantId);
        if (cancelled) return;
        const types = Array.isArray(s.entity_types) ? s.entity_types.filter((t) => t.trim()) : [];
        setSchemaTypes(types.length > 0 ? types : FALLBACK_SCHEMA_TYPES);
      } catch {
        if (!cancelled) setSchemaTypes(FALLBACK_SCHEMA_TYPES);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [graphPlaneDisabled, tenantId]);

  useEffect(() => {
    const q = searchQ.trim();
    if (graphPlaneDisabled || !q) {
      setSearchHits([]);
      setSearchErr("");
      return;
    }
    const ac = new AbortController();
    const t = window.setTimeout(() => {
      void (async () => {
        try {
          const r = await graph.searchEntities({
            tenant_id: tenantId,
            q,
            label: searchLabel || undefined,
            limit: 20,
          });
          if (ac.signal.aborted) return;
          setSearchHits(r.entities ?? []);
          setSearchErr("");
        } catch (e) {
          if (ac.signal.aborted) return;
          setSearchHits([]);
          setSearchErr(toUserFacingError(e, { subject: "Graph search", action: "search entities" }));
        }
      })();
    }, 200);
    return () => {
      ac.abort();
      window.clearTimeout(t);
    };
  }, [graphPlaneDisabled, searchQ, searchLabel, tenantId]);

  useEffect(() => {
    if (graphPlaneDisabled || entityId) {
      setTopN([]);
      setTopNErr("");
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const r = await graph.entityRiskTop({ tenant_id: tenantId, limit: 20 });
        if (cancelled) return;
        setTopN(r.entities ?? []);
        setTopNErr("");
      } catch (e) {
        if (cancelled) return;
        setTopN([]);
        setTopNErr(toUserFacingError(e, { subject: "Entity risk", action: "load top scored entities" }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [graphPlaneDisabled, entityId, tenantId]);

  useEffect(() => {
    seedLoadGenRef.current += 1;
    if (graphPlaneDisabled || !entityId) {
      if (!entityId) {
        setLoaded(null);
        setPruneNote("");
        setSelectedId(null);
        setSelectedNode(null);
        setHighlightIds(undefined);
        setDossierMessage(null);
      }
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPruneNote("");
    setHighlightIds(undefined);
    setDossierMessage(null);
    void (async () => {
      try {
        const sub = await graph.subgraph(entityId, tenantId, depth);
        if (cancelled) return;
        const pruned = await pruneSubgraphAsync(sub.nodes, sub.edges, entityId, LINK_ANALYSIS_MAX_NODES);
        if (cancelled) return;
        setLoaded({ nodes: pruned.nodes, edges: pruned.edges });
        if (pruned.originalNodeCount > pruned.prunedNodeCount) {
          setPruneNote(pruneBanner(pruned.originalNodeCount, pruned.prunedNodeCount, sub.nodes.length));
        }
        const seed = pruned.nodes.find((n) => n.id === entityId) ?? {
          id: entityId,
          labels: [],
          properties: {},
        };
        setSelectedId(entityId);
        setSelectedNode(seed);
      } catch (e) {
        if (cancelled) return;
        setLoaded(null);
        setError(toUserFacingError(e, { subject: "Entity graph", action: "load graph exploration data" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [graphPlaneDisabled, entityId, tenantId, depth]);

  const expandNode = useCallback(
    async (id: string) => {
      if (graphPlaneDisabled || !id || !tenantId || !entityId) return;
      if (loadingRef.current) return;
      const seedAtStart = entityId;
      const genAtStart = seedLoadGenRef.current;
      setExpanding(true);
      setError(null);
      try {
        const extra = await graph.subgraph(id, tenantId, 1);
        if (seedLoadGenRef.current !== genAtStart) return;
        const merged = mergeSubgraphs(
          seedAtStart,
          loadedRef.current ?? { nodes: [], edges: [] },
          extra,
          LINK_ANALYSIS_MAX_NODES,
        );
        setLoaded({ nodes: merged.nodes, edges: merged.edges });
        if (merged.originalNodeCount > merged.prunedNodeCount) {
          setPruneNote(pruneBanner(merged.originalNodeCount, merged.prunedNodeCount, merged.originalNodeCount));
        }
      } catch (e) {
        if (seedLoadGenRef.current !== genAtStart) return;
        setError(toUserFacingError(e, { subject: "Entity graph", action: "expand neighborhood" }));
      } finally {
        setExpanding(false);
      }
    },
    [entityId, graphPlaneDisabled, tenantId],
  );

  const pathFromSeed = useCallback(async () => {
    if (graphPlaneDisabled || !entityId || !selectedId || selectedId === entityId) return;
    setDossierMessage(null);
    try {
      const expl = await graph.pathExplain({
        tenant_id: tenantId,
        subject: entityId,
        target: selectedId,
        depth: 3,
      });
      if (!expl.paths || expl.paths.length === 0) {
        setDossierMessage("No path found between seed and this entity.");
        return;
      }
      setHighlightIds(pathNodeIds(expl, entityId, selectedId));
    } catch (e) {
      setDossierMessage(toUserFacingError(e, { subject: "Path", action: "explain path from seed" }));
    }
  }, [entityId, graphPlaneDisabled, selectedId, tenantId]);

  const loadRings = useCallback(async () => {
    if (graphPlaneDisabled || !tenantId) return;
    setAnalyzing(true);
    try {
      const [comm, rings] = await Promise.allSettled([
        graph.communities(tenantId),
        graph.fraudRings(tenantId),
      ]);
      if (comm.status === "fulfilled") setCommunities(comm.value.communities ?? []);
      if (rings.status === "fulfilled") setFraudRings(rings.value.rings ?? []);
    } finally {
      setAnalyzing(false);
    }
  }, [graphPlaneDisabled, tenantId]);

  const highlightMembers = useCallback(
    (ids: string[]) => {
      if (!loaded) return;
      const onCanvas = new Set(loaded.nodes.map((n) => n.id));
      setHighlightIds(new Set(ids.filter((id) => onCanvas.has(id))));
    },
    [loaded],
  );

  const histogram = useMemo(() => (loaded ? typeHistogram(loaded.nodes) : []), [loaded]);

  const graphData = useMemo(() => {
    if (!loaded) return null;
    const filtered = filterWorkspaceNodes(loaded.nodes, loaded.edges, filter);
    return {
      nodes: paintStoredRisk(filtered.nodes),
      links: toForceGraphLinks(filtered.edges),
    };
  }, [filter, loaded]);

  const largeGraph = (graphData?.nodes.length ?? 0) > 800;
  const disabled = graphPlaneDisabled;

  return (
    <div className="p-6 h-full flex flex-col gap-4 animate-fade-in min-h-0">
      <div className="flex items-center justify-between gap-4">
        <PageTitle module="graph">Graph</PageTitle>
        <p className="text-sm text-gray-500">
          Trace layered payouts in{" "}
          <Link to="/graph/mule-path" className="text-brand-400 hover:text-brand-300 font-medium">
            Mule path
          </Link>{" "}
          (User A → mule → cash-out).
        </p>
      </div>

      {graphPlaneDisabled ? (
        <div className="text-sm text-rose-100/95 bg-rose-950/40 border border-rose-500/35 rounded-lg px-3 py-2.5 space-y-1">
          <p>
            <strong className="text-rose-200">Graph plane disabled</strong> — subgraph and graph analytics requests are
            paused (failover toggle). Re-enable when JanusGraph / graph-service latency recovers.
          </p>
          <Link
            to="/ops/failover-toggles"
            className="text-xs font-semibold text-brand-300 hover:text-brand-200 underline-offset-2 hover:underline"
          >
            Open failover toggles
          </Link>
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-500 flex flex-col gap-1 relative min-w-[220px] flex-1">
          Search
          <input
            type="text"
            value={searchQ}
            disabled={disabled}
            placeholder="Entity id contains…"
            onChange={(e) => setSearchQ(e.target.value)}
            className={inputClass}
            autoComplete="off"
          />
          {searchErr ? (
            <span className="absolute left-0 top-full mt-1 z-20 text-[11px] text-rose-300 bg-rose-950/90 border border-rose-500/30 rounded px-2 py-1">
              {searchErr}
            </span>
          ) : null}
          {searchHits.length > 0 ? (
            <ul className="absolute left-0 right-0 top-full mt-1 z-20 max-h-56 overflow-y-auto rounded-lg border border-surface-600 bg-surface-900 shadow-xl">
              {searchHits.map((hit) => (
                <li key={`${hit.tenant_id}:${hit.entity_id}`}>
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2 text-xs hover:bg-surface-800 text-gray-200"
                    onClick={() => selectEntity(hit.entity_id, hit.tenant_id || tenantId)}
                  >
                    <span className="font-mono">{hit.entity_id}</span>
                    <span className="text-gray-500 ml-2">{hit.labels?.[0] ?? "Custom"}</span>
                    {hit.scored && hit.risk_score != null ? (
                      <span className="text-amber-300/90 ml-2 font-mono">{hit.risk_score.toFixed(0)}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </label>
        <div className="flex flex-wrap gap-1.5 items-center pb-1">
          {schemaTypes.map((t) => (
            <button
              key={t}
              type="button"
              disabled={disabled}
              className={chipClass(searchLabel === t)}
              onClick={() => setSearchLabel((prev) => (prev === t ? null : t))}
            >
              {t}
            </button>
          ))}
        </div>
        <label className="text-xs text-gray-500 flex flex-col gap-1">
          Tenant
          <input
            type="text"
            value={tenantDraft}
            disabled={disabled}
            onChange={(e) => setTenantDraft(e.target.value)}
            onBlur={() => {
              const t = tenantDraft.trim() || defaultTenantId();
              if (t !== tenantId) writeUrl({ entityId, tenantId: t, depth });
            }}
            className={`${inputClass} w-36`}
          />
        </label>
        <label className="text-xs text-gray-500 flex flex-col gap-1">
          Depth
          <input
            type="number"
            min={1}
            max={5}
            value={depth}
            disabled={disabled}
            onChange={(e) => {
              const n = Number.parseInt(e.target.value, 10);
              const next = Number.isFinite(n) ? Math.min(5, Math.max(1, n)) : 2;
              writeUrl({ entityId, tenantId, depth: next });
            }}
            className={`${inputClass} w-20`}
          />
        </label>
      </div>

      {error ? (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      ) : null}
      {pruneNote ? (
        <p className="text-xs text-amber-200/90 border border-amber-500/30 rounded-md px-3 py-2 bg-amber-500/10">
          {pruneNote}
        </p>
      ) : null}

      {!entityId && !disabled ? (
        <div className="flex-1 min-h-0 bg-surface-900 border border-surface-700 rounded-xl p-4 overflow-y-auto">
          <h2 className="text-sm font-semibold text-gray-200 mb-2">Top scored entities</h2>
          {topNErr ? <p className="text-sm text-rose-300">{topNErr}</p> : null}
          {!topNErr && topN.length === 0 ? (
            <p className="text-sm text-gray-500">No scored entities for this tenant.</p>
          ) : (
            <ul className="space-y-1">
              {topN.map((row) => (
                <li key={row.entity_id}>
                  <button
                    type="button"
                    className="w-full flex items-center justify-between gap-3 px-3 py-2 rounded-lg hover:bg-surface-800 text-left"
                    onClick={() => selectEntity(row.entity_id)}
                  >
                    <span className="font-mono text-sm text-gray-200">{row.entity_id}</span>
                    <span className="text-xs text-gray-500">{row.labels?.[0] ?? "Custom"}</span>
                    <span className="font-mono text-sm text-amber-300/90">{row.risk_score.toFixed(0)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 grid gap-3" style={{ gridTemplateColumns: "140px 1fr 280px" }}>
          <aside className="min-h-0 overflow-y-auto space-y-3 bg-surface-900 border border-surface-700 rounded-xl p-2">
            <div>
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Types</h3>
                <button
                  type="button"
                  className="text-[10px] text-brand-400 hover:text-brand-300"
                  onClick={() => setFilter((f) => ({ ...f, types: null }))}
                >
                  All
                </button>
              </div>
              <ul className="space-y-0.5">
                {histogram.map((row) => {
                  const on = filter.types?.includes(row.label) ?? false;
                  return (
                    <li key={row.label}>
                      <button
                        type="button"
                        className={`w-full flex items-center gap-1.5 px-1 py-0.5 rounded text-[11px] ${
                          on ? "bg-brand-600/20 text-brand-200" : "text-gray-400 hover:bg-surface-800"
                        }`}
                        onClick={() =>
                          setFilter((f) => ({
                            ...f,
                            types: f.types?.length === 1 && f.types[0] === row.label ? null : [row.label],
                          }))
                        }
                      >
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: NODE_COLORS[row.label] ?? "#6b7280" }}
                        />
                        <span className="truncate">{row.label}</span>
                        <span className="ml-auto tabular-nums text-gray-500">{row.count}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
            <label className="text-[10px] text-gray-500 flex flex-col gap-1">
              Min risk
              <input
                type="number"
                min={0}
                max={100}
                value={minRiskText}
                disabled={disabled}
                placeholder="any"
                onChange={(e) => {
                  const v = e.target.value;
                  setMinRiskText(v);
                  const n = Number.parseFloat(v);
                  setFilter((f) => ({
                    ...f,
                    minRisk: v.trim() === "" || !Number.isFinite(n) ? null : n,
                  }));
                }}
                className={`${inputClass} py-1 text-xs`}
              />
            </label>
            <label className="flex items-center gap-1.5 text-[11px] text-gray-400">
              <input
                type="checkbox"
                checked={filter.scoredOnly}
                disabled={disabled}
                onChange={(e) => setFilter((f) => ({ ...f, scoredOnly: e.target.checked }))}
              />
              Scored only
            </label>
            <label className="flex items-center gap-1.5 text-[11px] text-gray-400">
              <input
                type="checkbox"
                checked={filter.growthOnly}
                disabled={disabled}
                onChange={(e) => setFilter((f) => ({ ...f, growthOnly: e.target.checked }))}
              />
              Growth
            </label>
            <button
              type="button"
              disabled={disabled || analyzing || !tenantId}
              onClick={() => void loadRings()}
              className="w-full px-2 py-1.5 bg-amber-600/80 hover:bg-amber-600 disabled:opacity-50 text-white text-[11px] font-medium rounded-lg"
            >
              {analyzing ? "Loading…" : "Rings / communities"}
            </button>
            {communities.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-[10px] font-semibold text-gray-400">Communities</h3>
                {communities.map((c) => (
                  <button
                    key={c.community_id}
                    type="button"
                    className="w-full text-left bg-surface-800 rounded px-1.5 py-1 text-[10px] text-gray-400 hover:bg-surface-700"
                    onClick={() => highlightMembers(c.member_ids)}
                  >
                    C{c.community_id} · {c.member_count}
                  </button>
                ))}
              </div>
            ) : null}
            {fraudRings.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-[10px] font-semibold text-red-400">Rings</h3>
                {fraudRings.map((r, i) => (
                  <button
                    key={i}
                    type="button"
                    className="w-full text-left bg-surface-800 border border-red-500/20 rounded px-1.5 py-1 text-[10px] text-gray-400 hover:bg-surface-700"
                    onClick={() => highlightMembers(r.ring_members)}
                  >
                    {r.ring_size} · {r.aggregate_tags.join(", ") || "ring"}
                  </button>
                ))}
              </div>
            ) : null}
          </aside>

          <div className="min-h-0 min-w-0 bg-surface-900 border border-surface-700 rounded-xl relative overflow-hidden">
            {loading ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-surface-950/40">
                <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : null}
            {graphData && graphData.nodes.length > 0 ? (
              <LinkAnalysisForceGraph
                graphData={graphData}
                largeGraph={largeGraph}
                highlightIds={highlightIds}
                onNodeClick={(id, node) => {
                  setSelectedId(id);
                  setSelectedNode(node);
                  setDossierMessage(null);
                }}
                onNodeDoubleClick={(id) => {
                  void expandNode(id);
                }}
              />
            ) : !loading && !error ? (
              <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm px-4 text-center">
                {disabled
                  ? "Graph plane is disabled"
                  : entityId
                    ? "Subgraph returned no nodes for this entity and depth."
                    : "Enter an entity ID and tenant to explore the graph"}
              </div>
            ) : null}
            {expanding ? (
              <p className="absolute bottom-2 left-2 text-[11px] text-gray-400">Expanding…</p>
            ) : null}
          </div>

          <aside className="min-h-0 flex flex-col bg-surface-900 border border-surface-700 rounded-xl overflow-hidden">
            {selectedId ? (
              <div className="shrink-0 border-b border-surface-800 px-2 py-2 space-y-2">
                <div className="flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    disabled={disabled || expanding || loading}
                    onClick={() => void expandNode(selectedId)}
                    className="px-2 py-1 text-[11px] font-medium rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white"
                  >
                    Expand
                  </button>
                  {selectedId !== entityId ? (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => void pathFromSeed()}
                      className="px-2 py-1 text-[11px] font-medium rounded-lg bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-200"
                    >
                      Path from seed
                    </button>
                  ) : null}
                </div>
                {dossierMessage ? <p className="text-[11px] text-amber-200/90">{dossierMessage}</p> : null}
              </div>
            ) : null}
            <div className="flex-1 min-h-0">
              <GraphContextPanel
                embedded
                open={Boolean(selectedId)}
                onClose={() => {
                  setSelectedId(null);
                  setSelectedNode(null);
                  setDossierMessage(null);
                }}
                tenantId={tenantId}
                entityId={selectedId}
                nodeHint={selectedNode ?? undefined}
              />
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
