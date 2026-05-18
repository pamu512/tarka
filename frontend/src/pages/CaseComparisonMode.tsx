import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  cases,
  decisions,
  graph,
  type Case,
  type EntityRiskResult,
  type InferenceContext,
  normalizeInferenceContext,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import PriorityBadge from "../components/PriorityBadge";
import StatusBadge from "../components/StatusBadge";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

type AuditSnapshot = {
  decision: string;
  score: number;
  rule_hits: string[];
  tags: string[];
  inference: InferenceContext | null;
};

export type PaneSnapshot = {
  caseData: Case;
  audit: AuditSnapshot | null;
  graphRisk: EntityRiskResult | null;
};

type PaneState = {
  loading: boolean;
  error: string | null;
  snapshot: PaneSnapshot | null;
};

function intersectSorted(a: readonly string[], b: readonly string[]): string[] {
  const bs = new Set(b.map((x) => x.trim()).filter(Boolean));
  const out: string[] = [];
  const seen = new Set<string>();
  for (const x of a) {
    const t = x.trim();
    if (!t || !bs.has(t) || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out.sort((x, y) => x.localeCompare(y));
}

function useCasePane(caseId: string, tenantId: string): PaneState {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<PaneSnapshot | null>(null);

  useEffect(() => {
    if (!caseId.trim()) {
      setSnapshot(null);
      setError(null);
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSnapshot(null);

    void (async () => {
      try {
        const c = await cases.get(caseId.trim(), tenantId.trim());
        if (cancelled) return;
        const [auditRow, risk] = await Promise.all([
          c.trace_id
            ? decisions.getAudit(c.trace_id, tenantId.trim(), { detail_level: "analyst" }).catch(() => null)
            : Promise.resolve(null),
          graph.entityRisk(c.entity_id, tenantId.trim()).catch(() => null),
        ]);
        if (cancelled) return;
        const audit: AuditSnapshot | null = auditRow
          ? {
              decision: auditRow.decision,
              score: auditRow.score,
              rule_hits: auditRow.rule_hits ?? [],
              tags: auditRow.tags ?? [],
              inference: normalizeInferenceContext(auditRow.inference_context),
            }
          : null;
        setSnapshot({ caseData: c, audit, graphRisk: risk });
      } catch (e) {
        if (!cancelled) {
          setError(toUserFacingError(e, { subject: "Case comparison", action: "load case workspace" }));
          setSnapshot(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [caseId, tenantId]);

  return { loading, error, snapshot };
}

function CasePaneBody({ snapshot, tenantId }: { snapshot: PaneSnapshot; tenantId: string }): ReactElement {
  const { caseData: c, audit, graphRisk } = snapshot;
  const ic = audit?.inference ?? null;

  return (
    <div className="space-y-4 text-sm">
      <div>
        <Link
          to={`/cases/${encodeURIComponent(c.id)}?tenant_id=${encodeURIComponent(tenantId)}`}
          className="text-lg font-semibold text-gray-100 hover:text-brand-300 leading-snug"
        >
          {c.title}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-500 font-mono">{c.id}</span>
          <StatusBadge status={c.status} />
          <PriorityBadge priority={c.priority} />
        </div>
      </div>

      <dl className="grid grid-cols-1 gap-2 text-xs border border-surface-700 rounded-lg p-3 bg-surface-950/40">
        <div className="flex justify-between gap-2">
          <dt className="text-gray-500">Entity</dt>
          <dd className="font-mono text-gray-200 truncate">{c.entity_id}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-gray-500">Trace</dt>
          <dd className="font-mono text-gray-200 truncate">{c.trace_id || "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-gray-500">Queue score</dt>
          <dd className="text-gray-200 tabular-nums">{c.queue_score != null ? c.queue_score.toFixed(1) : "—"}</dd>
        </div>
        {c.case_type ? (
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Case type</dt>
            <dd className="text-gray-200">{c.case_type}</dd>
          </div>
        ) : null}
      </dl>

      {c.labels.length > 0 ? (
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5">Labels</div>
          <div className="flex flex-wrap gap-1.5">
            {c.labels.map((lb) => (
              <span
                key={lb}
                className="text-[11px] px-2 py-0.5 rounded-full bg-surface-800 text-gray-300 border border-surface-600"
              >
                {lb}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {audit ? (
        <div className="rounded-lg border border-surface-700 p-3 space-y-2 bg-surface-950/30">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Latest audit</div>
          <p className="text-gray-200">
            <span className="capitalize font-semibold">{audit.decision}</span>
            <span className="text-gray-500"> · Score </span>
            <span className="font-mono tabular-nums">{audit.score.toFixed(1)}</span>
            <span className="text-gray-500">/100</span>
          </p>
          {audit.rule_hits.length > 0 ? (
            <div>
              <div className="text-[10px] text-gray-500 mb-1">Rule hits</div>
              <ul className="font-mono text-[11px] text-gray-300 space-y-0.5 list-disc list-inside max-h-32 overflow-y-auto">
                {audit.rule_hits.slice(0, 14).map((h) => (
                  <li key={h} className="truncate">
                    {h}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-gray-500">No decision audit on this trace.</p>
      )}

      {ic ? (
        <div className="rounded-lg border border-surface-700 p-3 space-y-2 bg-surface-950/30">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Inference signals</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
            <dt className="text-gray-500">Velocity 24h</dt>
            <dd className="text-gray-200 font-mono tabular-nums text-right">{ic.velocity_events_24h}</dd>
            <dt className="text-gray-500">Graph risk</dt>
            <dd className="text-gray-200 font-mono tabular-nums text-right">{ic.graph_risk_score.toFixed(3)}</dd>
            <dt className="text-gray-500">Geo stress</dt>
            <dd className="text-gray-200 font-mono tabular-nums text-right">{ic.geo_consistency_risk.toFixed(3)}</dd>
            <dt className="text-gray-500">Impossible travel</dt>
            <dd className="text-gray-200 font-mono tabular-nums text-right">{ic.impossible_travel_risk.toFixed(3)}</dd>
            <dt className="text-gray-500">External OSINT</dt>
            <dd className="text-gray-200 font-mono tabular-nums text-right">{ic.external_signal_score.toFixed(3)}</dd>
            <dt className="text-gray-500">Colocation</dt>
            <dd className="text-gray-200 font-mono tabular-nums text-right">{ic.colocation_risk.toFixed(3)}</dd>
          </dl>
          {ic.ml_summary ? (
            <p className="text-[11px] text-gray-400 leading-snug border-t border-surface-700 pt-2">{ic.ml_summary}</p>
          ) : null}
        </div>
      ) : null}

      {graphRisk ? (
        <div className="rounded-lg border border-surface-700 p-3 text-xs bg-surface-950/30">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-2">Graph risk</div>
          <p className="text-gray-200 tabular-nums">
            Score <span className="font-mono">{graphRisk.risk_score.toFixed(3)}</span>
            <span className="text-gray-500"> · Community </span>
            <span className="font-mono">{graphRisk.community_size}</span>
          </p>
          {graphRisk.risk_factors.length > 0 ? (
            <p className="text-[11px] text-gray-400 mt-1">Factors: {graphRisk.risk_factors.slice(0, 6).join(", ")}</p>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-gray-500">No graph risk payload for this entity.</p>
      )}
    </div>
  );
}

function PatternHighlights({ left, right }: { left: PaneSnapshot | null; right: PaneSnapshot | null }): ReactElement | null {
  const hints = useMemo(() => {
    if (!left || !right) return null;
    const la = left.audit;
    const ra = right.audit;
    const sharedLabels = intersectSorted(left.caseData.labels, right.caseData.labels);
    const sharedRules = la && ra ? intersectSorted(la.rule_hits, ra.rule_hits) : [];
    const sameEntity = left.caseData.entity_id === right.caseData.entity_id;
    const li = la?.inference ?? null;
    const ri = ra?.inference ?? null;
    const sharedOsint =
      li && ri ? intersectSorted(li.external_signal_providers, ri.external_signal_providers) : [];
    return { sharedLabels, sharedRules, sameEntity, sharedOsint, li, ri };
  }, [left, right]);

  if (!left || !right || !hints) return null;

  return (
    <section
      aria-label="Coordinated pattern hints"
      className="shrink-0 rounded-xl border border-brand-500/25 bg-brand-500/[0.06] px-4 py-3 space-y-3"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-200/90">
        Pattern hints (marketplace coordination)
      </h3>
      <ul className="text-sm text-gray-200 space-y-2 list-none">
        {hints.sameEntity ? (
          <li className="flex gap-2">
            <span className="text-amber-400 shrink-0">●</span>
            <span>
              <strong className="text-gray-100">Same marketplace actor</strong> — both cases anchor on entity{" "}
              <code className="text-[11px] text-brand-200">{left.caseData.entity_id}</code>.
            </span>
          </li>
        ) : (
          <li className="flex gap-2">
            <span className="text-gray-500 shrink-0">○</span>
            <span>Different entities — linkage may still exist via graph or device cohort (open full cases).</span>
          </li>
        )}
        {hints.sharedLabels.length > 0 ? (
          <li className="flex gap-2">
            <span className="text-emerald-400 shrink-0">●</span>
            <span>
              <strong className="text-gray-100">Shared labels</strong> ({hints.sharedLabels.length}):{" "}
              {hints.sharedLabels.join(", ")}
            </span>
          </li>
        ) : null}
        {hints.sharedRules.length > 0 ? (
          <li className="flex gap-2">
            <span className="text-emerald-400 shrink-0">●</span>
            <span>
              <strong className="text-gray-100">Shared rule hits</strong> ({hints.sharedRules.length}):{" "}
              <span className="font-mono text-[11px] text-gray-300">{hints.sharedRules.slice(0, 8).join(" · ")}</span>
            </span>
          </li>
        ) : null}
        {hints.sharedOsint.length > 0 ? (
          <li className="flex gap-2">
            <span className="text-emerald-400 shrink-0">●</span>
            <span>
              <strong className="text-gray-100">Shared OSINT providers</strong>: {hints.sharedOsint.join(", ")}
            </span>
          </li>
        ) : null}
      </ul>
      {hints.li && hints.ri ? (
        <p className="text-[11px] text-gray-500 leading-snug">
          Velocity delta:{" "}
          <span className="font-mono text-gray-400">
            {hints.li.velocity_events_24h} vs {hints.ri.velocity_events_24h}
          </span>
          {" · "}
          Graph risk delta:{" "}
          <span className="font-mono text-gray-400">
            {(hints.li.graph_risk_score - hints.ri.graph_risk_score).toFixed(3)}
          </span>
        </p>
      ) : null}
    </section>
  );
}

function PaneShell({
  label,
  caseId,
  tenantId,
  state,
  onSetAsA,
  onSetAsB,
}: {
  label: string;
  caseId: string;
  tenantId: string;
  state: PaneState;
  onSetAsA: (id: string) => void;
  onSetAsB: (id: string) => void;
}): ReactElement {
  const { loading, error, snapshot } = state;

  return (
    <section
      aria-label={`${label} workspace`}
      className="flex min-h-0 min-w-0 flex-1 flex-col rounded-xl border border-surface-700 bg-surface-900/50 overflow-hidden"
    >
      <div className="shrink-0 border-b border-surface-700 px-4 py-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</h2>
        {snapshot ? (
          <div className="flex flex-wrap gap-2 text-[11px]">
            <button
              type="button"
              className="px-2 py-1 rounded border border-surface-600 text-gray-300 hover:bg-surface-800"
              onClick={() => onSetAsA(snapshot.caseData.id)}
            >
              Set as A
            </button>
            <button
              type="button"
              className="px-2 py-1 rounded border border-surface-600 text-gray-300 hover:bg-surface-800"
              onClick={() => onSetAsB(snapshot.caseData.id)}
            >
              Set as B
            </button>
            <Link
              to={`/cases/${encodeURIComponent(snapshot.caseData.id)}?tenant_id=${encodeURIComponent(tenantId)}`}
              className="px-2 py-1 rounded border border-brand-500/40 text-brand-300 hover:bg-brand-500/10"
            >
              Full case
            </Link>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 space-y-4">
        {!caseId.trim() ? (
          <p className="text-sm text-gray-500">Enter a case id in the bar above and apply to load this column.</p>
        ) : loading ? (
          <div className="flex justify-center py-16">
            <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="space-y-2 text-sm text-rose-300">
            <p>{error}</p>
            <SupportIdHint
              message={error}
              className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
              buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
            />
          </div>
        ) : snapshot ? (
          <CasePaneBody snapshot={snapshot} tenantId={tenantId} />
        ) : null}
      </div>
    </section>
  );
}

export default function CaseComparisonMode(): ReactElement {
  const [searchParams, setSearchParams] = useSearchParams();
  const { tenantId, setTenantId } = useTenantEnvironment();

  const caseA = searchParams.get("case_a")?.trim() ?? "";
  const caseB = searchParams.get("case_b")?.trim() ?? "";

  const [draftA, setDraftA] = useState(caseA);
  const [draftB, setDraftB] = useState(caseB);

  useEffect(() => {
    setDraftA(caseA);
    setDraftB(caseB);
  }, [caseA, caseB]);

  useEffect(() => {
    const t = searchParams.get("tenant_id")?.trim();
    if (t && t !== tenantId) setTenantId(t);
  }, [searchParams, setTenantId, tenantId]);

  const left = useCasePane(caseA, tenantId);
  const right = useCasePane(caseB, tenantId);

  const pageMeta = useMemo(() => {
    if (!left.snapshot && !right.snapshot) {
      return { title: "Case comparison", subtitle: "Side-by-side marketplace attack patterns" };
    }
    const a = left.snapshot?.caseData.title ?? "Case A";
    const b = right.snapshot?.caseData.title ?? "Case B";
    return { title: "Case comparison", subtitle: `${a.slice(0, 28)}${a.length > 28 ? "…" : ""} · ${b.slice(0, 28)}${b.length > 28 ? "…" : ""}` };
  }, [left.snapshot, right.snapshot]);
  useRegisterPageMeta(pageMeta);

  const applyIds = useCallback(() => {
    const sp = new URLSearchParams();
    const a = draftA.trim();
    const b = draftB.trim();
    if (a) sp.set("case_a", a);
    if (b) sp.set("case_b", b);
    sp.set("tenant_id", tenantId.trim() || "demo");
    setSearchParams(sp, { replace: true });
  }, [draftA, draftB, setSearchParams, tenantId]);

  const swapSides = useCallback(() => {
    const sp = new URLSearchParams(searchParams);
    const a = sp.get("case_a")?.trim() ?? "";
    const b = sp.get("case_b")?.trim() ?? "";
    if (a) sp.set("case_b", a);
    else sp.delete("case_b");
    if (b) sp.set("case_a", b);
    else sp.delete("case_a");
    if (!sp.get("tenant_id")) sp.set("tenant_id", tenantId.trim() || "demo");
    setSearchParams(sp, { replace: true });
  }, [searchParams, setSearchParams, tenantId]);

  const setAFromId = useCallback(
    (id: string) => {
      setDraftA(id);
      const sp = new URLSearchParams(searchParams);
      sp.set("case_a", id);
      if (!sp.get("tenant_id")) sp.set("tenant_id", tenantId.trim() || "demo");
      setSearchParams(sp, { replace: true });
    },
    [searchParams, setSearchParams, tenantId],
  );

  const setBFromId = useCallback(
    (id: string) => {
      setDraftB(id);
      const sp = new URLSearchParams(searchParams);
      sp.set("case_b", id);
      if (!sp.get("tenant_id")) sp.set("tenant_id", tenantId.trim() || "demo");
      setSearchParams(sp, { replace: true });
    },
    [searchParams, setSearchParams, tenantId],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-6 animate-fade-in">
      <div className="shrink-0 space-y-2">
        <PageTitle module="cases">Comparison mode</PageTitle>
        <p className="text-sm text-gray-500 max-w-3xl leading-relaxed">
          Open two cases side-by-side to spot <span className="text-gray-400">coordinated marketplace attacks</span>: shared
          actors, overlapping policy hits, and divergent velocity or graph stress. Use{" "}
          <strong className="text-gray-400">Set as A/B</strong> from a loaded pane to pivot quickly while triaging rings.
        </p>
      </div>

      <div className="shrink-0 flex flex-wrap items-end gap-3 rounded-xl border border-surface-700 bg-surface-900/40 p-4">
        <label className="flex flex-col gap-1 text-xs text-gray-500 min-w-[12rem]">
          Tenant
          <input
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500 flex-1 min-w-[11rem]">
          Case A id
          <input
            value={draftA}
            onChange={(e) => setDraftA(e.target.value)}
            className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono"
            placeholder="UUID…"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500 flex-1 min-w-[11rem]">
          Case B id
          <input
            value={draftB}
            onChange={(e) => setDraftB(e.target.value)}
            className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono"
            placeholder="UUID…"
          />
        </label>
        <button
          type="button"
          onClick={applyIds}
          className="text-xs font-semibold px-4 py-2 rounded-lg bg-brand-600/25 text-brand-200 border border-brand-500/40 hover:bg-brand-600/35"
        >
          Apply
        </button>
        <button
          type="button"
          onClick={swapSides}
          disabled={!caseA.trim() && !caseB.trim()}
          className="text-xs font-semibold px-4 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-40"
        >
          Swap A ↔ B
        </button>
        <Link to="/cases" className="text-xs text-brand-400 hover:text-brand-300 pb-2">
          Cases queue
        </Link>
      </div>

      <PatternHighlights left={left.snapshot} right={right.snapshot} />

      <div className="min-h-0 flex-1 grid grid-cols-1 xl:grid-cols-2 gap-4">
        <PaneShell
          label="Case A"
          caseId={caseA}
          tenantId={tenantId}
          state={left}
          onSetAsA={setAFromId}
          onSetAsB={setBFromId}
        />
        <PaneShell
          label="Case B"
          caseId={caseB}
          tenantId={tenantId}
          state={right}
          onSetAsA={setAFromId}
          onSetAsB={setBFromId}
        />
      </div>
    </div>
  );
}
