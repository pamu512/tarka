import type { EditorProps } from "@monaco-editor/react";
import type { ComponentType, LazyExoticComponent } from "react";
import { lazy, Suspense, useCallback, useState } from "react";
import { executeFeatureStoreDdl } from "../../api/client";

const MonacoEditor: LazyExoticComponent<ComponentType<EditorProps>> = lazy(() =>
  import("@monaco-editor/react").then((m) => ({ default: m.Editor })),
);

const DEFAULT_SQL = `-- Single ClickHouse DDL statement (admin, gated server-side).
-- Allowed prefixes: CREATE MATERIALIZED VIEW, CREATE TABLE, CREATE VIEW, ALTER TABLE, DROP TABLE, DROP VIEW, DROP DICTIONARY
CREATE TABLE IF NOT EXISTS tarka_feature_ddl_example (id Int64, tenant_id String) ENGINE = Memory;
`;

export default function FeatureStoreDdlEditorTab() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const hasApiKey = Boolean((import.meta.env.VITE_API_KEY as string | undefined)?.trim());

  const run = useCallback(async () => {
    setBusy(true);
    setSuccess(null);
    setError(null);
    try {
      const out = await executeFeatureStoreDdl(sql);
      if (!out.ok) {
        setError("Server returned success HTTP status but body was missing ok: true (no silent failures).");
        return;
      }
      setSuccess("DDL executed on ClickHouse (HTTP 200, executed: true).");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e ?? "Unknown error");
      setError(msg);
    } finally {
      setBusy(false);
    }
  }, [sql]);

  return (
    <div className="space-y-4 text-gray-200">
      <div>
        <h2 className="text-lg font-semibold text-gray-100">Feature Store DDL console</h2>
        <p className="mt-1 text-sm text-gray-500 max-w-3xl">
          Runs exactly one gated ClickHouse DDL statement via{" "}
          <code className="text-gray-400">POST /v1/feature-store/ddl/execute</code> (admin only). Compilation and
          driver errors from ClickHouse are returned verbatim in the response and shown below — nothing is swallowed.
        </p>
        {!hasApiKey ? (
          <p className="mt-2 text-sm text-amber-200/90 rounded-lg border border-amber-500/30 bg-amber-950/20 px-3 py-2">
            Set <code className="text-amber-100">VITE_API_KEY</code> to match decision-api <code className="text-amber-100">API_KEYS</code> so the browser can send{" "}
            <code className="text-amber-100">x-api-key</code>; otherwise requests will 401.
          </p>
        ) : null}
      </div>

      <div className="rounded-xl border border-surface-700 overflow-hidden bg-surface-950">
        <Suspense
          fallback={
            <div className="h-[420px] flex items-center justify-center text-gray-500 text-sm">Loading Monaco editor…</div>
          }
        >
          <MonacoEditor
            height="420px"
            defaultLanguage="sql"
            theme="vs-dark"
            value={sql}
            onChange={(v: string | undefined) => setSql(v ?? "")}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              wordWrap: "on",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
            }}
          />
        </Suspense>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !sql.trim()}
          onClick={() => void run()}
          className="rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-brand-500 disabled:opacity-40"
        >
          {busy ? "Executing…" : "Execute DDL on ClickHouse"}
        </button>
        <span className="text-xs text-gray-600">One statement only; server rejects SYSTEM / TRUNCATE / DROP DATABASE / multiple statements.</span>
      </div>

      {success ? (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 px-4 py-3 text-sm text-emerald-100">{success}</div>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/25 px-4 py-3 text-sm text-rose-100">
          <div className="font-semibold text-rose-200 mb-1">ClickHouse / validation error</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-rose-50/95">{error}</pre>
        </div>
      ) : null}
    </div>
  );
}
