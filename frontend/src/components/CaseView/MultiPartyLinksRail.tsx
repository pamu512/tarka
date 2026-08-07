import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { cases, type MultiPartyLink, type MultiPartyLinksResponse } from "../../api/client";
import { normalizeRiskScore } from "../../domain/linkAnalysisGraph";
import { toUserFacingError } from "../../utils/userFacingErrors";

const DEFAULT_DEPTH = 3;

export type MultiPartyLinksRailState = {
  data: MultiPartyLinksResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

export function useMultiPartyLinksRailState(
  caseId: string,
  tenantId: string,
  enabled = true,
): MultiPartyLinksRailState {
  const [data, setData] = useState<MultiPartyLinksResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!enabled || !caseId.trim() || !tenantId.trim()) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await cases.multiPartyLinks(caseId, tenantId, { depth: DEFAULT_DEPTH });
      setData(res);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Multi-party links", action: "load collusion links" }));
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantId, enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, loading, error, reload };
}

function RoleChips({ roles }: { roles: string[] }) {
  if (roles.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {roles.map((role) => (
        <span
          key={role}
          className="rounded-full border border-violet-500/35 bg-violet-950/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-200/90"
        >
          {role}
        </span>
      ))}
    </div>
  );
}

function LinkRow({
  row,
  tenantId,
}: {
  row: MultiPartyLink;
  tenantId: string;
}) {
  const graphHref = `/graph?entity_id=${encodeURIComponent(row.entity_id)}&tenant_id=${encodeURIComponent(tenantId)}`;

  return (
    <li className="rounded-lg border border-surface-700/90 bg-surface-950/60 px-2.5 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <RoleChips roles={row.roles} />
        <span className="shrink-0 text-[10px] tabular-nums text-gray-500">
          d={row.distance}{" "}
          <span className="text-gray-600">·</span>{" "}
          <span className="text-amber-200/90">
            {(normalizeRiskScore(row.propagated_risk_score) ?? 0).toFixed(0)}
          </span>
        </span>
      </div>
      <div className="mt-1 font-mono text-[11px] text-gray-200 break-all leading-snug">{row.entity_id}</div>
      {row.path_description ? (
        <p className="mt-1 text-[10px] text-gray-500 leading-snug line-clamp-2" title={row.path_description}>
          {row.path_description}
        </p>
      ) : null}
      {row.shared_signals.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {row.shared_signals.map((sig) => (
            <span
              key={sig}
              className="rounded bg-surface-800 px-1.5 py-0.5 text-[10px] text-gray-400"
            >
              {sig}
            </span>
          ))}
        </div>
      ) : null}
      {row.cases.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {row.cases.map((c) => {
            const caseHref = `/cases/${encodeURIComponent(c.case_id)}?tenant_id=${encodeURIComponent(tenantId)}`;
            const labelParts = [c.case_id, c.status.replace(/_/g, " ")];
            if (c.disposition_reason) labelParts.push(c.disposition_reason);
            return (
              <li key={c.case_id}>
                <Link
                  to={caseHref}
                  className="inline-block text-[10px] font-medium text-brand-400 hover:text-brand-300"
                >
                  {labelParts.join(" · ")} →
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-[10px] text-gray-600">No linked cases for this entity.</p>
      )}
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
  caseId,
}: {
  state: MultiPartyLinksRailState;
  tenantId: string;
  caseId: string;
}) {
  const { loading, error, data, reload } = state;

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-violet-500/40 border-t-violet-400" />
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
  if (data?.degraded) {
    return (
      <div className="space-y-2 px-1 py-2 text-[11px] text-amber-200/90">
        <p>
          Graph unavailable — multi-party neighbors could not be loaded
          {data.degraded_reason ? ` (${data.degraded_reason.replace(/_/g, " ")})` : ""}.
        </p>
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
  if (!data || data.links.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-gray-500 px-1 py-2">
        No multi-party collusion links in the graph window for case{" "}
        <span className="font-mono text-gray-600">{caseId.slice(0, 12)}…</span>, or neighbors have no
        linked cases in this tenant.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {data.links.map((row) => (
        <LinkRow key={row.entity_id} row={row} tenantId={tenantId} />
      ))}
    </ul>
  );
}

function PanelHeader({ entityId }: { entityId: string }) {
  return (
    <div className="space-y-1">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Multi-party links</h2>
      <p className="text-[11px] leading-snug text-gray-500">
        Graph neighbors with marketplace roles and linked cases (collusion rail).
      </p>
      {entityId ? (
        <p className="text-[10px] font-mono text-gray-600 truncate" title={entityId}>
          Anchor: {entityId}
        </p>
      ) : null}
    </div>
  );
}

/** Collapsible block for narrow viewports — lives inside the main case column. */
export function MultiPartyLinksMobilePanel({
  caseId,
  tenantId,
  entityId,
  state,
}: {
  caseId: string;
  tenantId: string;
  entityId: string;
  state: MultiPartyLinksRailState;
}) {
  const countLabel =
    state.loading ? "…" : state.error ? "!" : state.data?.degraded ? "↓" : String(state.data?.links.length ?? 0);

  return (
    <details className="xl:hidden rounded-xl border border-surface-700 bg-surface-900/80 open:shadow-lg shadow-black/20">
      <summary className="cursor-pointer select-none list-none px-4 py-3 text-sm font-medium text-gray-200 hover:bg-surface-800/60 [&::-webkit-details-marker]:hidden flex items-center justify-between gap-2">
        <span>Multi-party collusion links</span>
        <span className="text-[10px] font-normal text-violet-400/90">{countLabel}</span>
      </summary>
      <div className="border-t border-surface-800 px-4 pb-4 pt-3 space-y-3">
        <PanelHeader entityId={entityId} />
        <SidebarBody state={state} tenantId={tenantId} caseId={caseId} />
      </div>
    </details>
  );
}

/** Fixed rail on xl+ — sibling to knowledge graph rail and Shadow AI. */
export function MultiPartyLinksDesktopRail({
  caseId,
  tenantId,
  state,
}: {
  caseId: string;
  tenantId: string;
  state: MultiPartyLinksRailState;
}) {
  const entityId = state.data?.entity_id ?? "";

  return (
    <aside
      className="hidden xl:flex w-[min(18rem,calc(26vw))] shrink-0 flex-col border-surface-700 bg-surface-950/90 xl:border-l"
      aria-label="Multi-party collusion links"
      data-testid="multi-party-links-rail"
    >
      <div className="border-b border-surface-800 px-3 py-3">
        <PanelHeader entityId={entityId} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <SidebarBody state={state} tenantId={tenantId} caseId={caseId} />
      </div>
    </aside>
  );
}
