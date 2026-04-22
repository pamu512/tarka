import { useEffect, useState } from "react";
import { decisions } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

export default function OpsCounters() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [gov, setGov] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [cat, g] = await Promise.all([decisions.counterCatalog(), decisions.governance()]);
        setData(cat as Record<string, unknown>);
        setGov(g as Record<string, unknown>);
      } catch (e) {
        setErr(toUserFacingError(e, { subject: "Counter catalog", action: "load counter catalog and governance" }));
      }
    })();
  }, []);

  const counters = (data?.counters as Array<Record<string, unknown>> | undefined) ?? [];

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="compliance">Counters &amp; velocity catalog</PageTitle>
        <p className="text-sm text-gray-500">Declarative manifest + human titles (OSS ops)</p>
      </div>
      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300 space-y-1">
          <p>{err}</p>
          <SupportIdHint
            message={err}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}
      {gov && (
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm text-gray-300">
          <div>
            Inference schema:{" "}
            <span className="font-mono text-brand-300">{String(gov.inference_schema_version ?? "")}</span>
          </div>
          {gov.counter_catalog && typeof gov.counter_catalog === "object" ? (
            <div className="mt-2 text-xs text-gray-500">
              {(gov.counter_catalog as { note?: string }).note ||
                `See ${(gov.counter_catalog as { endpoint?: string }).endpoint ?? "GET /v1/internal/counters/catalog"}`}
            </div>
          ) : null}
        </div>
      )}
      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-800 text-left text-gray-400">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Title</th>
              <th className="px-3 py-2">Category</th>
              <th className="px-3 py-2">Window</th>
              <th className="px-3 py-2">Kind</th>
            </tr>
          </thead>
          <tbody>
            {counters.map((c) => (
              <tr key={String(c.name)} className="border-t border-surface-700/80">
                <td className="px-3 py-2 font-mono text-xs text-brand-300">{String(c.name ?? "")}</td>
                <td className="px-3 py-2 text-gray-200">{String(c.title ?? c.name ?? "")}</td>
                <td className="px-3 py-2 text-gray-400">{String(c.category ?? "—")}</td>
                <td className="px-3 py-2 text-gray-400 tabular-nums">
                  {c.window_seconds != null ? `${String(c.window_seconds)}s` : "—"}
                </td>
                <td className="px-3 py-2 text-gray-500">{String(c.kind ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">
        Redis key version: set <span className="font-mono">AGG_KEY_VERSION</span> for migrations. Offline replay:{" "}
        <span className="font-mono">scripts/replay/run_offline_parity.py</span>.
      </p>
    </div>
  );
}
