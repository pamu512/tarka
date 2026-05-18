import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { graph, type RiskPropagationResult } from "../../api/client";
import { normalizeSimilarEntities } from "../../utils/similarGraphEntities";
import { toUserFacingError } from "../../utils/userFacingErrors";

const PROPAGATION_DEPTH = 3;

export type KnowledgeGraphSidebarState = {
  similar: RiskPropagationResult[];
  loading: boolean;
  error: string | null;
  reload: () => void;
};

export function useKnowledgeGraphSidebarState(
  entityId: string,
  tenantId: string,
  enabled = true,
): KnowledgeGraphSidebarState {
  const [similar, setSimilar] = useState<RiskPropagationResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!enabled || !entityId.trim() || !tenantId.trim()) {
      setSimilar([]);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await graph.riskPropagation(entityId, tenantId, PROPAGATION_DEPTH);
      setSimilar(normalizeSimilarEntities(entityId, res.entities ?? []));
    } catch (e) {
      setSimilar([]);
      setError(toUserFacingError(e, { subject: "Knowledge graph", action: "load similar entities" }));
    } finally {
      setLoading(false);
    }
  }, [entityId, tenantId, enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { similar, loading, error, reload };
}

function SimilarEntityRow({
  row,
  tenantId,
}: {
  row: RiskPropagationResult;
  tenantId: string;
}) {
  const label = row.entity_labels?.[0] ?? "Entity";
  const graphHref = `/graph?entity_id=${encodeURIComponent(row.entity_id)}&tenant_id=${encodeURIComponent(tenantId)}`;

  return (
    <li className="rounded-lg border border-surface-700/90 bg-surface-950/60 px-2.5 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-cyan-400/90">{label}</span>
        <span className="shrink-0 text-[10px] tabular-nums text-gray-500">
          d={row.distance}{" "}
          <span className="text-gray-600">·</span>{" "}
          <span className="text-amber-200/90">{(row.propagated_risk_score * 100).toFixed(0)}</span>
        </span>
      </div>
      <div className="mt-1 font-mono text-[11px] text-gray-200 break-all leading-snug">{row.entity_id}</div>
      {row.path_description ? (
        <p className="mt-1 text-[10px] text-gray-500 leading-snug line-clamp-2" title={row.path_description}>
          {row.path_description}
        </p>
      ) : null}
      <Link
        to={graphHref}
        className="mt-2 inline-block text-[10px] font-medium text-brand-400 hover:text-brand-300"
      >
        Open in Graph Explorer →
      </Link>
    </li>
  );
}

function SidebarBody({
  state,
  tenantId,
  entityId,
}: {
  state: KnowledgeGraphSidebarState;
  tenantId: string;
  entityId: string;
}) {
  const { loading, error, similar, reload } = state;

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-cyan-500/40 border-t-cyan-400" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="space-y-2 px-1 py-2 text-[11px] text-rose-200/90">
        <p>{error}</p>
        <button
          type="button"
          onClick={() => void reload()}
          className="rounded-md border border-surface-600 bg-surface-800 px-2 py-1 text-gray-200 hover:bg-surface-700"
        >
          Retry
        </button>
      </div>
    );
  }
  if (similar.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-gray-500 px-1 py-2">
        No neighboring vertices in the JanusGraph traversal window, or the anchor{" "}
        <span className="font-mono text-gray-600">{entityId}</span> is isolated in this tenant slice.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {similar.map((row) => (
        <SimilarEntityRow key={row.entity_id} row={row} tenantId={tenantId} />
      ))}
    </ul>
  );
}

function PanelHeader({ entityId }: { entityId: string }) {
  return (
    <div className="space-y-1">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Knowledge graph</h2>
      <p className="text-[11px] leading-snug text-gray-500">
        Similar entities linked in JanusGraph (risk propagation neighbors, hops ≤ {PROPAGATION_DEPTH}).
      </p>
      <p className="text-[10px] font-mono text-gray-600 truncate" title={entityId}>
        Anchor: {entityId}
      </p>
    </div>
  );
}

/** Collapsible block for narrow viewports — lives inside the main case column. */
export function KnowledgeGraphMobilePanel({
  entityId,
  tenantId,
  state,
}: {
  entityId: string;
  tenantId: string;
  state: KnowledgeGraphSidebarState;
}) {
  const countLabel =
    state.loading ? "…" : state.error ? "!" : String(state.similar.length);

  return (
    <details className="xl:hidden rounded-xl border border-surface-700 bg-surface-900/80 open:shadow-lg shadow-black/20">
      <summary className="cursor-pointer select-none list-none px-4 py-3 text-sm font-medium text-gray-200 hover:bg-surface-800/60 [&::-webkit-details-marker]:hidden flex items-center justify-between gap-2">
        <span>Similar entities (JanusGraph)</span>
        <span className="text-[10px] font-normal text-cyan-400/90">{countLabel}</span>
      </summary>
      <div className="border-t border-surface-800 px-4 pb-4 pt-3 space-y-3">
        <PanelHeader entityId={entityId} />
        <SidebarBody state={state} tenantId={tenantId} entityId={entityId} />
      </div>
    </details>
  );
}

/** Fixed rail on xl+ — sibling to main column and Shadow AI. */
export function KnowledgeGraphDesktopRail({
  entityId,
  tenantId,
  state,
}: {
  entityId: string;
  tenantId: string;
  state: KnowledgeGraphSidebarState;
}) {
  return (
    <aside
      className="hidden xl:flex w-[min(18rem,calc(26vw))] shrink-0 flex-col border-surface-700 bg-surface-950/90 xl:border-l"
      aria-label="Knowledge graph similar entities"
      data-testid="knowledge-graph-sidebar"
    >
      <div className="border-b border-surface-800 px-3 py-3">
        <PanelHeader entityId={entityId} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <SidebarBody state={state} tenantId={tenantId} entityId={entityId} />
      </div>
    </aside>
  );
}
