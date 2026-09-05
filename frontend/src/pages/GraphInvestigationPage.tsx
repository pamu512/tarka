import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  graph,
  type CommunityResult,
  type FraudRingResult,
  type GraphEdge,
  type GraphNode,
  type GraphSearchHit,
} from "../api/client";
import { GraphContextPanel } from "../components/GraphContextPanel";
import { LinkAnalysisForceGraph } from "../components/LinkAnalysisForceGraph";
import { FirstHourHint } from "../components/FirstHourHint";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useFailoverPlanes } from "../context/FailoverPlaneContext";
import {
  filterWorkspaceNodes,
  parseGraphWorkspaceParams,
  pathHighlightLinkKeys,
  pathNodeIds,
  searchHitMatchedOn,
  searchHitViaSubtitle,
  storedDisplayRisk,
  typeHistogram,
  buildPersonHuntGraph,
  decisionToastText,
  HUNT_LOOKBACK_DEFAULT_DAYS,
  HUNT_LOOKBACK_MAX_DAYS,
  HUNT_SEED_MAX,
  huntFetchTypes,
  lastOutcomeLabel,
  pickHomePerson,
  readLastPersonEntity,
  seedInstrumentFanout,
  writeLastPersonEntity,
  type GrowthPolicyWindow,
  type WorkspaceFilter,
} from "../domain/graphInvestigation";
import {
  LINK_ANALYSIS_MAX_NODES,
  type LinkAnalysisGraphNode,
  toForceGraphLinks,
} from "../domain/linkAnalysisGraph";
import { useToast } from "../context/ToastContext";
import { toUserFacingError } from "../utils/userFacingErrors";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";

const NODE_COLORS: Record<string, string> = {
  Person: "#3b82f6",
  Account: "#22c55e",
  Device: "#f97316",
  Payment: "#a855f7",
  Login: "#eab308",
  Session: "#14b8a6",
  Decision: "#94a3b8",
  Document: "#f59e0b",
  LicensePlate: "#d946ef",
  Email: "#06b6d4",
  Phone: "#6366f1",
  Ip: "#ec4899",
  IP: "#ec4899",
  Place: "#10b981",
  Address: "#84cc16",
  Card: "#f43f5e",
  List: "#0ea5e9",
};

const FALLBACK_SCHEMA_TYPES = [
  "Person",
  "Account",
  "Device",
  "Payment",
  "Login",
  "Session",
  "Decision",
  "Document",
  "LicensePlate",
  "Email",
  "Phone",
  "Ip",
  "IP",
  "Place",
  "Address",
  "Card",
  "List",
];

const EMPTY_FILTER: WorkspaceFilter = {
  types: null,
  minRisk: null,
  scoredOnly: false,
  growthOnly: false,
};


function paintStoredRisk(nodes: GraphNode[]): LinkAnalysisGraphNode[] {
  const stored = new Map(nodes.map((n) => [n.id, storedDisplayRisk(n)]));
  return nodes.map((n) => ({
    ...n,
    displayRisk: stored.get(n.id) ?? null,
    lastOutcome: lastOutcomeLabel(n),
  }));
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
  const { toast } = useToast();
  const { tenantId: workspaceTenantId, setTenantId: setWorkspaceTenantId } = useTenantEnvironment();
  const [params, setParams] = useSearchParams();
  const parsed = useMemo(
    () => parseGraphWorkspaceParams(params, workspaceTenantId),
    [params, workspaceTenantId],
  );
  const entityId = parsed.entityId.trim();
  const tenantId = parsed.tenantId.trim() || workspaceTenantId || "demo";
  const depth = parsed.depth;
  const lookbackDays = parsed.lookbackDays;
  const decisionId = parsed.decisionId;
  const leftoverId = params.get("leftover_id");
  const leftoverPack = params.get("pack");
  const leftoverHits = params.get("hits");

  const [searchQ, setSearchQ] = useState("");
  const [searchLabel, setSearchLabel] = useState<string | null>(null);
  const [searchHits, setSearchHits] = useState<GraphSearchHit[]>([]);
  const [searchErr, setSearchErr] = useState("");
  const [schemaTypes, setSchemaTypes] = useState<string[]>(FALLBACK_SCHEMA_TYPES);

  const [topN, setTopN] = useState<Array<{ entity_id: string; labels: string[]; risk_score: number }>>([]);
  const [topNErr, setTopNErr] = useState("");

  const [loaded, setLoaded] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanding, setExpanding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pruneNote, setPruneNote] = useState("");
  const [instrumentCapNote, setInstrumentCapNote] = useState("");

  const [filter, setFilter] = useState<WorkspaceFilter>(EMPTY_FILTER);
  const [minRiskText, setMinRiskText] = useState("");
  const [expandTypes, setExpandTypes] = useState<string[]>(huntFetchTypes());
  const [expandMax, setExpandMax] = useState(HUNT_SEED_MAX);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [dossierMessage, setDossierMessage] = useState<string | null>(null);
  const [highlightIds, setHighlightIds] = useState<Set<string> | undefined>(undefined);
  const [highlightLinkKeys, setHighlightLinkKeys] = useState<Set<string> | undefined>(undefined);

  const [communities, setCommunities] = useState<CommunityResult[]>([]);
  const [fraudRings, setFraudRings] = useState<FraudRingResult[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [growthWindows, setGrowthWindows] = useState<GrowthPolicyWindow[] | null>(null);
  const [tenantDraft, setTenantDraft] = useState(tenantId);
  const loadedRef = useRef(loaded);
  loadedRef.current = loaded;
  const loadingRef = useRef(loading);
  loadingRef.current = loading;
  const expandingRef = useRef(false);
  const seedLoadGenRef = useRef(0);
  const entityIdRef = useRef(entityId);
  entityIdRef.current = entityId;
  const tenantIdRef = useRef(tenantId);
  tenantIdRef.current = tenantId;
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  useEffect(() => {
    setTenantDraft(tenantId);
  }, [tenantId]);

  const writeUrl = useCallback(
    (next: {
      entityId: string;
      tenantId: string;
      depth: number;
      lookbackDays?: number;
      decisionId?: string;
    }) => {
      const sp = new URLSearchParams();
      if (next.entityId) {
        sp.set("entity_id", next.entityId);
        writeLastPersonEntity(next.tenantId, next.entityId);
      }
      if (next.tenantId) sp.set("tenant_id", next.tenantId);
      sp.set("depth", String(next.depth));
      const lb = next.lookbackDays ?? lookbackDays;
      if (lb !== HUNT_LOOKBACK_DEFAULT_DAYS) sp.set("lookback_days", String(lb));
      const dec = next.decisionId ?? decisionId;
      if (dec) sp.set("decision_id", dec);
      const keepLeftover = leftoverId?.trim();
      if (keepLeftover) sp.set("leftover_id", keepLeftover);
      if (leftoverPack) sp.set("pack", leftoverPack);
      if (leftoverHits) sp.set("hits", leftoverHits);
      setParams(sp, { replace: true });
    },
    [decisionId, leftoverHits, leftoverId, leftoverPack, lookbackDays, setParams],
  );

  useEffect(() => {
    if (entityId) writeLastPersonEntity(tenantId, entityId);
  }, [entityId, tenantId]);

  useEffect(() => {
    if (graphPlaneDisabled || entityId) return;
    const last = readLastPersonEntity(tenantId);
    if (!last) return;
    writeUrl({ entityId: last, tenantId, depth });
  }, [graphPlaneDisabled, entityId, tenantId, depth, writeUrl]);

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
        const rows = r.entities ?? [];
        setTopN(rows);
        setTopNErr("");
        if (!entityIdRef.current) {
          const home = pickHomePerson({ lastEntityId: readLastPersonEntity(tenantId), rows });
          if (home) writeUrl({ entityId: home, tenantId, depth });
        }
      } catch (e) {
        if (cancelled) return;
        setTopN([]);
        setTopNErr(toUserFacingError(e, { subject: "Entity risk", action: "load top scored entities" }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [graphPlaneDisabled, entityId, tenantId, depth, writeUrl]);

  useEffect(() => {
    seedLoadGenRef.current += 1;
    setCommunities([]);
    setFraudRings([]);
    if (graphPlaneDisabled || !entityId) {
      if (!entityId) {
        setLoaded(null);
        setPruneNote("");
        setInstrumentCapNote("");
        setSelectedId(null);
        setSelectedNode(null);
        setHighlightIds(undefined);
        setHighlightLinkKeys(undefined);
        setDossierMessage(null);
      }
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPruneNote("");
    setInstrumentCapNote("");
    setHighlightIds(undefined);
    setHighlightLinkKeys(undefined);
    setDossierMessage(null);
    void (async () => {
      try {
        const [sub, links] = await Promise.all([
          graph.subgraph(entityId, tenantId, depth, {
            lookbackDays,
            types: huntFetchTypes(),
          }),
          graph.entityLinks(entityId, tenantId),
        ]);
        if (cancelled) return;
        const fanout = seedInstrumentFanout(
          entityId,
          sub.nodes,
          sub.edges,
          links?.attention,
          {
            nowMs: Date.now(),
            lookbackDays,
            max: HUNT_SEED_MAX,
            pinDecisionId: decisionId,
          },
        );
        const instrumentIds = fanout.ids;
        setInstrumentCapNote(
          fanout.total > HUNT_SEED_MAX ? `Showing ${HUNT_SEED_MAX} of ${fanout.total} significant hops` : "",
        );
        const extras: typeof sub[] = [];
        if (instrumentIds.length > 0) {
          const settled = await Promise.allSettled(
            instrumentIds.map((id) =>
              graph.subgraph(id, tenantId, 1, { lookbackDays, types: huntFetchTypes() }),
            ),
          );
          if (cancelled) return;
          for (const row of settled) {
            if (row.status === "fulfilled") extras.push(row.value);
          }
        }
        const built = buildPersonHuntGraph(entityId, sub, extras, LINK_ANALYSIS_MAX_NODES);
        if (cancelled) return;
        setLoaded({ nodes: built.nodes, edges: built.edges });
        if (built.originalNodeCount > built.prunedNodeCount) {
          setPruneNote(pruneBanner(built.originalNodeCount, built.prunedNodeCount, sub.nodes.length));
        }
        const seed = built.nodes.find((n) => n.id === entityId) ?? {
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
  }, [decisionId, depth, entityId, graphPlaneDisabled, lookbackDays, tenantId]);

  const expandNode = useCallback(
    async (id: string) => {
      if (graphPlaneDisabled || !id || !tenantId || !entityId) return;
      if (loadingRef.current || expandingRef.current) return;
      const seedAtStart = entityId;
      const genAtStart = seedLoadGenRef.current;
      expandingRef.current = true;
      setExpanding(true);
      setError(null);
      try {
        const extra = await graph.subgraph(id, tenantId, 1, {
          lookbackDays,
          types: expandTypes,
        });
        if (seedLoadGenRef.current !== genAtStart) return;
        const others = extra.nodes.filter((node) => node.id !== id).slice(0, expandMax);
        const keep = new Set([id, ...others.map((node) => node.id)]);
        const capped = {
          nodes: extra.nodes.filter((node) => keep.has(node.id)),
          edges: extra.edges.filter((edge) => keep.has(edge.from_id) && keep.has(edge.to_id)),
        };
        const merged = buildPersonHuntGraph(
          seedAtStart,
          loadedRef.current ?? { nodes: [], edges: [] },
          [capped],
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
        expandingRef.current = false;
        setExpanding(false);
      }
    },
    [entityId, expandMax, expandTypes, graphPlaneDisabled, lookbackDays, tenantId],
  );

  const pathFromSeed = useCallback(async () => {
    if (graphPlaneDisabled || !entityId || !selectedId || selectedId === entityId) return;
    const genAtStart = seedLoadGenRef.current;
    const seedAtStart = entityId;
    const selectedAtStart = selectedId;
    setDossierMessage(null);
    try {
      const expl = await graph.pathExplain({
        tenant_id: tenantId,
        subject: entityId,
        target: selectedId,
        depth: 3,
      });
      if (seedLoadGenRef.current !== genAtStart) return;
      if (entityIdRef.current !== seedAtStart || selectedIdRef.current !== selectedAtStart) return;
      if (!expl.paths || expl.paths.length === 0) {
        setDossierMessage("No path found between seed and this entity.");
        return;
      }
      setHighlightIds(pathNodeIds(expl, seedAtStart, selectedAtStart));
      setHighlightLinkKeys(pathHighlightLinkKeys(expl));
    } catch (e) {
      if (seedLoadGenRef.current !== genAtStart) return;
      if (entityIdRef.current !== seedAtStart || selectedIdRef.current !== selectedAtStart) return;
      setDossierMessage(toUserFacingError(e, { subject: "Path", action: "explain path from seed" }));
    }
  }, [entityId, graphPlaneDisabled, selectedId, tenantId]);

  const loadRings = useCallback(async () => {
    if (graphPlaneDisabled || !tenantId) return;
    const tenantAtStart = tenantId;
    const genAtStart = seedLoadGenRef.current;
    setAnalyzing(true);
    try {
      const [comm, rings] = await Promise.allSettled([
        graph.communities(tenantId),
        graph.fraudRings(tenantId),
      ]);
      if (seedLoadGenRef.current !== genAtStart || tenantIdRef.current !== tenantAtStart) return;
      if (comm.status === "fulfilled") setCommunities(comm.value.communities ?? []);
      if (rings.status === "fulfilled") setFraudRings(rings.value.rings ?? []);
    } finally {
      setAnalyzing(false);
    }
  }, [graphPlaneDisabled, tenantId]);

  useEffect(() => {
    if (graphPlaneDisabled) {
      setGrowthWindows(null);
      return;
    }
    let cancelled = false;
    graph.growthPolicy().then(
      (row) => {
        if (!cancelled) setGrowthWindows(row.windows ?? null);
      },
      () => {
        if (!cancelled) setGrowthWindows(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [graphPlaneDisabled, tenantId]);

  const highlightMembers = useCallback(
    (ids: string[]) => {
      if (!loaded) return;
      const onCanvas = new Set(loaded.nodes.map((n) => n.id));
      setHighlightIds(new Set(ids.filter((id) => onCanvas.has(id))));
      setHighlightLinkKeys(undefined);
    },
    [loaded],
  );

  const histogram = useMemo(() => (loaded ? typeHistogram(loaded.nodes) : []), [loaded]);

  const graphData = useMemo(() => {
    if (!loaded) return null;
    const filtered = filterWorkspaceNodes(loaded.nodes, loaded.edges, {
      ...filter,
      growthWindows,
    });
    return {
      nodes: paintStoredRisk(filtered.nodes),
      links: toForceGraphLinks(filtered.edges),
    };
  }, [filter, growthWindows, loaded]);

  const largeGraph = (graphData?.nodes.length ?? 0) > 800;
  const disabled = graphPlaneDisabled;

  return (
    <div className="p-6 h-full flex flex-col gap-4 animate-fade-in min-h-0">
      <div className="flex items-center justify-between gap-4">
        <PageTitle module="graph">Hunt</PageTitle>
      </div>
      <FirstHourHint
        job="Hunt is who is connected to this person. Edges come from the receipt. Empty graph URL means hops are off — missing, not invented."
        nextTo="/leftovers"
        nextLabel="Leftovers"
      />

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
            placeholder="Id, email, device, IP…"
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
              {searchHits.map((hit) => {
                const viaLine = searchHitViaSubtitle(hit.via);
                const matchedOn = searchHitMatchedOn(hit.matched_on);
                return (
                  <li key={`${hit.tenant_id}:${hit.entity_id}`}>
                    <button
                      type="button"
                      className="w-full text-left px-3 py-2 text-xs hover:bg-surface-800 text-gray-200"
                      onClick={() => selectEntity(hit.entity_id, hit.tenant_id || tenantId)}
                    >
                      <span className="font-mono">{hit.entity_id}</span>
                      <span className="text-gray-500 ml-2">{hit.labels?.[0] ?? "Custom"}</span>
                      {matchedOn ? (
                        <span className="text-sky-300/90 ml-2">{matchedOn}</span>
                      ) : null}
                      {hit.scored && hit.risk_score != null ? (
                        <span className="text-amber-300/90 ml-2 font-mono">{hit.risk_score.toFixed(0)}</span>
                      ) : null}
                      <span className="text-gray-400 ml-2">{lastOutcomeLabel(hit)}</span>
                      {viaLine ? (
                        <div className="text-[11px] text-gray-500 mt-0.5">{viaLine}</div>
                      ) : null}
                    </button>
                  </li>
                );
              })}
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
              const t = tenantDraft.trim() || workspaceTenantId || "demo";
              if (t !== tenantId) {
                setWorkspaceTenantId(t);
                writeUrl({ entityId, tenantId: t, depth });
              }
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
        <label className="text-xs text-gray-500 flex flex-col gap-1">
          Lookback
          <select
            value={lookbackDays}
            disabled={disabled}
            onChange={(e) => {
              const n = Number.parseInt(e.target.value, 10);
              writeUrl({
                entityId,
                tenantId,
                depth,
                lookbackDays: Number.isFinite(n) ? n : HUNT_LOOKBACK_DEFAULT_DAYS,
              });
            }}
            className={`${inputClass} w-28`}
          >
            <option value={90}>90 days</option>
            <option value={365}>1 year</option>
            <option value={HUNT_LOOKBACK_MAX_DAYS}>Retention</option>
          </select>
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
      {instrumentCapNote ? (
        <p className="text-xs text-gray-400" data-testid="instrument-cap">
          {instrumentCapNote}
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
                  const on = filter.types == null || filter.types.includes(row.label);
                  return (
                    <li key={row.label}>
                      <button
                        type="button"
                        className={`w-full flex items-center gap-1.5 px-1 py-0.5 rounded text-[11px] ${
                          on ? "bg-brand-600/20 text-brand-200" : "text-gray-400 hover:bg-surface-800"
                        }`}
                        onClick={() =>
                          setFilter((f) => {
                            const all = histogram.map((h) => h.label);
                            const cur = f.types ?? all;
                            const next = cur.includes(row.label)
                              ? cur.filter((t) => t !== row.label)
                              : [...cur, row.label];
                            return {
                              ...f,
                              types: next.length === 0 || next.length === all.length ? null : next,
                            };
                          })
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
                highlightLinkKeys={highlightLinkKeys}
                onNodeClick={(id, node) => {
                  setSelectedId(id);
                  setSelectedNode(node);
                  setDossierMessage(null);
                  const line = decisionToastText(node);
                  if (line) {
                    const d = line.toLowerCase();
                    toast(
                      line,
                      d === "deny" || d === "flag" ? "error" : d === "allow" ? "success" : "info",
                    );
                  }
                }}
                onNodeDoubleClick={(id) => {
                  if (expandingRef.current) return;
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
                <div className="flex flex-wrap gap-1">
                  {[...huntFetchTypes(), "Login", "Session"].map((t) => {
                    const on = expandTypes.includes(t);
                    return (
                      <button
                        key={t}
                        type="button"
                        disabled={disabled}
                        className={chipClass(on)}
                        onClick={() =>
                          setExpandTypes((cur) =>
                            on ? cur.filter((x) => x !== t) : [...cur, t],
                          )
                        }
                      >
                        {t}
                      </button>
                    );
                  })}
                </div>
                <label className="text-[10px] text-gray-500 flex items-center gap-1.5">
                  Max
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={expandMax}
                    disabled={disabled}
                    onChange={(e) => {
                      const n = Number.parseInt(e.target.value, 10);
                      setExpandMax(Number.isFinite(n) ? Math.min(200, Math.max(1, n)) : HUNT_SEED_MAX);
                    }}
                    className={`${inputClass} py-0.5 w-16 text-[11px]`}
                  />
                </label>
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
                onSelectEntity={selectEntity}
                leftoverId={leftoverId}
                leftoverPack={leftoverPack}
                leftoverHits={leftoverHits}
                decisionId={decisionId}
                graphPlaneDisabled={graphPlaneDisabled}
              />
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
