import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  ruleEngine,
  rules as rulesApi,
  type RuleAstVersionDetail,
  type RuleAstVersionSummary,
  type RuleAstVersionsResponse,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { toUserFacingError } from "../utils/userFacingErrors";

export default function VersionedRuleControl(): ReactElement {
  const [catalog, setCatalog] = useState<RuleAstVersionsResponse | null>(null);
  const [detail, setDetail] = useState<RuleAstVersionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [rollingBack, setRollingBack] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  useRegisterPageMeta({ title: "Versioned rule control", subtitle: "AST snapshots · one-click rollback" });

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const res = await ruleEngine.listVersions();
      setCatalog(res);
      setError(null);
      setSelectedVersion((prev) => {
        if (prev != null && res.versions.some((v) => v.version === prev)) return prev;
        return res.active_version ?? res.versions[0]?.version ?? null;
      });
    } catch (e) {
      setCatalog(null);
      setError(toUserFacingError(e, { subject: "Rule versions", action: "load AST snapshots" }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    if (selectedVersion == null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    (async () => {
      try {
        const row = await ruleEngine.versionDetail(selectedVersion);
        if (!cancelled) setDetail(row);
      } catch {
        if (!cancelled) setDetail(null);
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedVersion]);

  const activeVersion = catalog?.active_version ?? null;

  const sortedVersions = useMemo(() => {
    if (!catalog) return [];
    return [...catalog.versions].sort((a, b) => b.version - a.version);
  }, [catalog]);

  const rollback = useCallback(
    async (row: RuleAstVersionSummary) => {
      if (row.is_active) return;
      const ok = window.confirm(
        `Rollback Rust rule engine to AST snapshot v${row.version}?\n\n` +
          `${row.rule_count} rules · hash ${row.ast_hash}\n\n` +
          "Live evaluation will hot-reload immediately.",
      );
      if (!ok) return;

      setRollingBack(row.version);
      setToast(null);
      try {
        const res = await ruleEngine.rollback(row.version);
        try {
          await rulesApi.reload();
        } catch {
          /* decision-api reload is best-effort when offline */
        }
        setToast(`Active snapshot is now v${res.active_version} (${res.rule_count} rules).`);
        await loadCatalog();
        setSelectedVersion(res.active_version);
      } catch (e) {
        setError(toUserFacingError(e, { subject: "Rollback", action: `activate v${row.version}` }));
      } finally {
        setRollingBack(null);
      }
    },
    [loadCatalog],
  );

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="rules">Versioned rule control</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Immutable <strong className="text-gray-400">fraud_rules</strong> AST snapshots power the Rust-backed evaluate
            path. Roll back to any prior version in one click — activates the row, reloads the in-process engine, and
            best-effort syncs legacy decision-api packs.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/rule-engine/v1/rules/versions · POST …/rollback/{"{version}"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Link to="/rules/visual" className="text-brand-400 hover:text-brand-300">
            Visual builder →
          </Link>
          <Link to="/rules" className="text-brand-400 hover:text-brand-300">
            Rule packs →
          </Link>
          <button
            type="button"
            onClick={() => void loadCatalog()}
            className="rounded-lg border border-surface-600 bg-surface-800 px-3 py-1.5 text-gray-200 hover:bg-surface-700"
          >
            Refresh
          </button>
        </div>
      </div>

      {toast ? (
        <div className="rounded-lg border border-emerald-500/35 bg-emerald-950/25 px-4 py-3 text-sm text-emerald-200">
          {toast}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.9fr)]">
        <section className="rounded-xl border border-surface-700 bg-surface-900/50 overflow-hidden">
          <div className="border-b border-surface-700 px-4 py-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-200">AST snapshot timeline</h2>
            <span className="text-[11px] text-gray-500 tabular-nums">
              active{" "}
              <span className="font-mono text-brand-300">{activeVersion != null ? `v${activeVersion}` : "—"}</span>
            </span>
          </div>

          {loading ? (
            <p className="px-4 py-10 text-sm text-gray-500">Loading versions…</p>
          ) : sortedVersions.length === 0 ? (
            <p className="px-4 py-10 text-sm text-gray-500">
              No versioned snapshots yet. Deploy rules via{" "}
              <code className="text-gray-400">POST /v1/rules/deploy</code> with RULE_ENGINE_DATABASE_URL configured.
            </p>
          ) : (
            <ul className="divide-y divide-surface-800">
              {sortedVersions.map((row) => (
                <li key={row.version}>
                  <div
                    className={`flex flex-wrap items-center gap-3 px-4 py-3 ${
                      selectedVersion === row.version ? "bg-brand-950/20" : "hover:bg-surface-900/80"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setSelectedVersion(row.version)}
                      className="flex-1 min-w-[200px] text-left"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-gray-100">v{row.version}</span>
                        {row.is_active ? (
                          <span className="rounded-full border border-emerald-500/40 bg-emerald-950/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-200">
                            Live
                          </span>
                        ) : null}
                      </div>
                      <p className="text-[11px] text-gray-500 mt-1 font-mono">
                        {row.rule_count} rules · {row.ast_hash}
                        {row.created_at ? ` · ${new Date(row.created_at).toLocaleString()}` : null}
                      </p>
                    </button>
                    <button
                      type="button"
                      disabled={row.is_active || rollingBack != null}
                      onClick={() => void rollback(row)}
                      className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold border transition-colors ${
                        row.is_active
                          ? "border-surface-700 text-gray-600 cursor-not-allowed"
                          : "border-brand-500/50 bg-brand-950/40 text-brand-200 hover:bg-brand-900/50"
                      }`}
                      title={row.is_active ? "Already active" : `Rollback to v${row.version}`}
                    >
                      {rollingBack === row.version ? "Rolling back…" : row.is_active ? "Active" : "Rollback"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className="rounded-xl border border-surface-700 bg-surface-900/60 flex flex-col min-h-[280px]">
          <div className="border-b border-surface-700 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-200">AST payload</h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {selectedVersion != null ? `Snapshot v${selectedVersion}` : "Select a version"}
            </p>
          </div>
          <pre className="flex-1 overflow-auto p-4 text-[11px] font-mono text-gray-400 leading-relaxed whitespace-pre-wrap break-all">
            {detailLoading
              ? "Loading…"
              : detail
                ? JSON.stringify(detail.rules_payload, null, 2)
                : "Click a version to inspect the immutable rules_payload JSON."}
          </pre>
        </aside>
      </div>
    </div>
  );
}
