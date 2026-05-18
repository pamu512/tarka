import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";

import {
  integrations,
  type ReviewRingCluster,
  type ReviewRingClustersResponse,
} from "../api/client";
import { ReviewRingBadge } from "../components/analytics/ReviewRingBadge";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

export default function ReviewRingClusters(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<ReviewRingClustersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [minRingSize, setMinRingSize] = useState(3);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useRegisterPageMeta({ title: "Review rings", subtitle: "5-product overlap clusters" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.reviewRings({
        tenant_id: tenantId,
        min_ring_size: minRingSize,
        limit: 12,
      });
      setData(res);
      setExpandedId(res.clusters[0]?.cluster_id ?? null);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Review rings", action: "load clusters" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId, minRingSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const clusters = useMemo(() => data?.clusters ?? [], [data]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="analytics">Review ring clusters</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Groups users who have <strong className="text-gray-300">all reviewed the same 5 products</strong> — a
            classic fake-review and astroturfing pattern. Each cluster shows the shared product set and member overlap
            signals.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/analytics/review-rings
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      <form
        className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 flex flex-wrap gap-3 items-end"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <label className="text-xs text-gray-500 block min-w-[140px]">
          Min ring size
          <input
            type="number"
            min={2}
            max={15}
            value={minRingSize}
            onChange={(e) => setMinRingSize(Number(e.target.value) || 3)}
            className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm font-mono text-gray-100"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white"
        >
          Apply
        </button>
      </form>

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Clustering review overlap…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Clusters" value={data.summary.cluster_count} />
            <Stat label="Users in rings" value={data.summary.users_in_rings} accent="cyan" />
            <Stat label="High suspicion" value={data.summary.high_suspicion_clusters} />
            <Stat label="Largest ring" value={data.summary.largest_ring_size} />
          </div>

          {data.signals.length > 0 ? (
            <ul className="rounded-xl border border-cyan-500/25 bg-cyan-950/10 px-4 py-3 text-sm text-cyan-100/90 list-disc pl-5 space-y-1">
              {data.signals.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : null}

          <p className="text-[11px] text-gray-600">
            Rule: exactly <span className="font-mono text-gray-400">{data.rules.shared_product_count}</span> shared
            products · min ring size {data.rules.min_ring_size}
          </p>

          <div className="space-y-3">
            {clusters.map((cluster) => (
              <ClusterCard
                key={cluster.cluster_id}
                cluster={cluster}
                expanded={expandedId === cluster.cluster_id}
                onToggle={() =>
                  setExpandedId((id) => (id === cluster.cluster_id ? null : cluster.cluster_id))
                }
              />
            ))}
            {clusters.length === 0 ? (
              <p className="text-sm text-gray-500 py-12 text-center">No review rings match this filter.</p>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: string }): ReactElement {
  const tone =
    accent === "cyan" ? "border-cyan-500/35 bg-cyan-950/20" : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">{value}</p>
    </div>
  );
}

function ClusterCard({
  cluster,
  expanded,
  onToggle,
}: {
  cluster: ReviewRingCluster;
  expanded: boolean;
  onToggle: () => void;
}): ReactElement {
  return (
    <section className="rounded-xl border border-surface-700 bg-surface-900/50 overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-left hover:bg-surface-800/40"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-gray-200">{cluster.cluster_id}</span>
          <ReviewRingBadge memberCount={cluster.member_count} />
          <span className="text-[10px] text-gray-500 tabular-nums">suspicion {cluster.suspicion_score}</span>
        </div>
        <div className="text-xs text-gray-400 text-right">
          <p>
            <strong className="text-gray-200">{cluster.member_count}</strong> reviewers · 5 shared SKUs
          </p>
          <p className="text-[10px] mt-0.5">{expanded ? "Collapse" : "Expand"}</p>
        </div>
      </button>

      {expanded ? (
        <div className="px-4 pb-4 space-y-4 border-t border-surface-700">
          <div>
            <h3 className="text-[10px] uppercase tracking-wide text-gray-500 mb-2">Shared products</h3>
            <ul className="flex flex-wrap gap-2">
              {cluster.shared_products.map((p) => (
                <li
                  key={p.product_id}
                  className="rounded-lg border border-surface-600 bg-surface-950/60 px-2.5 py-1.5 text-[11px] max-w-[220px]"
                >
                  <p className="font-mono text-[9px] text-gray-600">{p.product_id}</p>
                  <p className="text-gray-200 leading-snug">{p.title}</p>
                  <p className="text-[9px] text-gray-500 mt-0.5">
                    {p.category} · {p.seller_id}
                  </p>
                </li>
              ))}
            </ul>
          </div>

          {cluster.signals.length > 0 ? (
            <p className="text-[10px] text-cyan-300/80 font-mono">{cluster.signals.join(" · ")}</p>
          ) : null}

          <div>
            <h3 className="text-[10px] uppercase tracking-wide text-gray-500 mb-2">Members</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-gray-500 uppercase tracking-wide">
                  <tr className="border-b border-surface-700">
                    <th className="text-left py-2 pr-3">User</th>
                    <th className="text-right py-2 px-3">Avg rating</th>
                    <th className="text-left py-2 pl-3">Review span</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-800 text-gray-300">
                  {cluster.members.map((m) => (
                    <tr key={m.user_id}>
                      <td className="py-2 pr-3">
                        <p className="font-mono text-gray-200">{m.user_id}</p>
                        <p className="text-[10px] text-gray-600">{m.display_name}</p>
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums">{m.avg_rating_given}</td>
                      <td className="py-2 pl-3 font-mono text-[10px] text-gray-500">
                        {new Date(m.first_shared_review_at).toLocaleDateString()} →{" "}
                        {new Date(m.last_shared_review_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
