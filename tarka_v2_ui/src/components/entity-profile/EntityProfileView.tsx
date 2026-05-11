"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { EntityProfileResponse } from "@/types/entity-profile";

type Props = {
  userId: string;
};

function formatMoney(n: number): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(n);
}

function GraphNeighborhood({ profile }: { profile: EntityProfileResponse }) {
  const nodes = profile.graph_viz?.nodes ?? [];
  const links = profile.graph_viz?.links ?? [];
  const backend = profile.graph_viz?.backend ?? profile.graph_fragment?.backend ?? "—";

  const layout = useMemo(() => {
    const cx = 200;
    const cy = 200;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const pos = new Map<string, { x: number; y: number }>();
    const anchor = nodes.find((n) => n.kind === "User");
    if (anchor) {
      pos.set(anchor.id, { x: cx, y: cy });
    }
    const satellites = nodes.filter((n) => n.kind !== "User");
    satellites.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(satellites.length, 1) - Math.PI / 2;
      const r = n.kind === "IP" ? 150 : 110;
      pos.set(n.id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
    });
    return { pos, cx, cy, byId };
  }, [nodes]);

  if (!nodes.length) {
    return (
      <p className="text-sm text-slate-500">
        No graph sketch — neighborhood empty or anchor missing in JanusGraph / Neo4j.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>Graph backend: {String(backend)}</span>
        <span>{links.length} edges in fragment</span>
      </div>
      <svg
        viewBox="0 0 400 400"
        className="h-[min(420px,55vh)] w-full max-w-xl rounded-lg border border-slate-800 bg-slate-900/40"
        role="img"
        aria-label="User neighborhood graph fragment"
      >
        {links.map((l, idx) => {
          const a = layout.pos.get(l.source);
          const b = layout.pos.get(l.target);
          if (!a || !b) return null;
          return (
            <line
              key={`${l.source}-${l.target}-${idx}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="rgb(71 85 105)"
              strokeWidth={1.5}
            />
          );
        })}
        {nodes.map((n) => {
          const p = layout.pos.get(n.id);
          if (!p) return null;
          const fill =
            n.kind === "User" ? "rgb(56 189 248)" : n.kind === "Device" ? "rgb(251 191 36)" : "rgb(167 139 250)";
          const r = n.kind === "User" ? 14 : 10;
          return (
            <g key={n.id}>
              <circle cx={p.x} cy={p.y} r={r} fill={fill} opacity={0.9} />
              <text
                x={p.x}
                y={p.y + r + 14}
                textAnchor="middle"
                className="fill-slate-400 text-[10px]"
              >
                {n.kind}
              </text>
              <title>{n.label}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function EntityProfileView({ userId }: Props) {
  const [data, setData] = useState<EntityProfileResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await fetch(
        `/api/v1/marketplace/users/${encodeURIComponent(userId)}/entity-profile`,
        { cache: "no-store" },
      );
      const j = (await r.json()) as EntityProfileResponse & { error?: string };
      if (!r.ok) {
        setData(null);
        setErr(typeof j.error === "string" ? j.error : r.statusText || "Request failed");
        return;
      }
      setData(j as EntityProfileResponse);
    } catch (e) {
      setData(null);
      setErr(e instanceof Error ? e.message : "fetch failed");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const duck = data?.duckdb_metrics;
  const spend = typeof duck?.total_spend === "number" ? duck.total_spend : 0;
  const listings = typeof duck?.listing_count === "number" ? duck.listing_count : 0;
  const promo = duck?.promo_success_rate;
  const promoPct =
    typeof promo === "number" && !Number.isNaN(promo) ? `${Math.round(promo * 100)}%` : "—";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <header className="border-b border-slate-800 pb-3">
        <h1 className="text-lg font-semibold tracking-tight text-slate-100">Entity Explorer</h1>
        <p className="text-xs text-slate-500">
          Prompt 84 — unified view: Postgres case · JanusGraph/Neo4j neighborhood · DuckDB marketplace
          stats · Shadow executive summary (when live).
        </p>
        <p className="mt-1 font-mono text-sm text-cyan-400">user_id: {userId}</p>
      </header>

      {loading && <p className="text-sm text-slate-400">Loading profile…</p>}
      {err && (
        <div className="rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-200">
          {err}
        </div>
      )}

      {data && (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_18rem] lg:grid-rows-[auto_1fr]">
          <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:col-span-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              DuckDB — marketplace metrics
            </h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-3">
              <div>
                <p className="text-xs text-slate-500">Spend (matched txns)</p>
                <p className="mt-1 text-2xl font-semibold text-slate-100">{formatMoney(spend)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Distinct listings</p>
                <p className="mt-1 text-2xl font-semibold text-slate-100">{listings}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Promo success rate</p>
                <p className="mt-1 text-2xl font-semibold text-slate-100">{promoPct}</p>
                {typeof duck?.promo_denominator === "number" && duck.promo_denominator > 0 && (
                  <p className="text-[11px] text-slate-500">from {duck.promo_denominator} promo rows</p>
                )}
              </div>
            </div>
          </section>

          <section className="flex min-h-[22rem] flex-col rounded-lg border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              JanusGraph / Neo4j — neighborhood fragment
            </h2>
            <div className="mt-3 flex min-h-0 flex-1 items-center justify-center">
              <GraphNeighborhood profile={data} />
            </div>
          </section>

          <aside className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:row-span-1">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Shadow AI — executive summary
            </h2>
            <div className="min-h-0 flex-1 overflow-auto rounded border border-slate-800/80 bg-slate-950/60 p-3 text-sm leading-relaxed text-slate-300">
              {data.shadow_executive_summary?.available ? (
                <p className="whitespace-pre-wrap">
                  {String(data.shadow_executive_summary.ai_reasoning || "—")}
                </p>
              ) : (
                <p className="text-slate-500">
                  {String(
                    data.shadow_executive_summary?.message ||
                      data.shadow_executive_summary?.error ||
                      "Shadow not live for this request (set SHADOW_AGENT_URL and clear ORCHESTRATOR_ENTITY_PROFILE_SKIP_SHADOW), or check orchestrator logs.",
                  )}
                </p>
              )}
            </div>
            <div className="text-[11px] text-slate-600">
              Gate: confirm <code className="text-slate-400">data_sources.shadow_live</code> when calling
              live <code className="text-slate-400">/v1/analyze</code>.
            </div>
          </aside>

          <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:col-span-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Postgres — lifecycle case
            </h2>
            {data.lifecycle_case ? (
              <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-slate-500">case_id</dt>
                  <dd className="font-mono text-slate-200">{data.lifecycle_case.case_id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">status</dt>
                  <dd>
                    <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-cyan-300">
                      {data.lifecycle_case.status}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">priority</dt>
                  <dd className="text-slate-200">{data.lifecycle_case.priority}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">opened_at</dt>
                  <dd className="font-mono text-xs text-slate-400">{data.lifecycle_case.opened_at ?? "—"}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                No lifecycle case row for this <code className="text-slate-400">user_link_key</code> (expected
                when no BLOCK/FLAG/SHADOW_REVIEW ingests yet).
              </p>
            )}
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 font-mono text-[11px] text-slate-500 lg:col-span-2">
            <span className="text-slate-600">data_sources:</span>{" "}
            {JSON.stringify(data.data_sources, null, 0).replace(/\n/g, " ")}
          </section>
        </div>
      )}
    </div>
  );
}
