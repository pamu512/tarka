"use client";

import { useEffect, useMemo } from "react";
import useSWR from "swr";
import { HealthCard } from "@/components/health/HealthCard";
import { getHealthFullUrl } from "@/lib/health-full-url";
import type { HealthFullResponse } from "@/types/health-full";

const POLL_MS = 800;

const fetcher = async (url: string): Promise<HealthFullResponse> => {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    const snippet = await res.text().catch(() => "");
    throw new Error(
      `${res.status} ${res.statusText}${snippet ? `: ${snippet.slice(0, 200)}` : ""}`.trim(),
    );
  }
  return res.json() as Promise<HealthFullResponse>;
};

export function HealthGrid() {
  const url = useMemo(() => getHealthFullUrl(), []);

  const { data, error, isLoading, isValidating, mutate } = useSWR(url, fetcher, {
    refreshInterval: POLL_MS,
    revalidateOnFocus: true,
    dedupingInterval: 400,
    shouldRetryOnError: true,
    errorRetryInterval: 800,
  });

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") void mutate();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [mutate]);

  const orchestrator = data?.orchestrator;
  const ruleEngine = data?.rule_engine;
  const shadowAi = data?.shadow_ai;

  return (
    <section aria-label="System health" className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-sm font-semibold text-slate-100">System health</h1>
          <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-slate-500">
            Aggregated from <code className="text-slate-400">GET /health/full</code>.             Polls about every {(POLL_MS / 1000).toFixed(1).replace(/\.0$/, "")}s.
          </p>
        </div>
        {isValidating ? (
          <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
            Refreshing…
          </span>
        ) : null}
      </header>

      {error ? (
        <p className="rounded-md border border-red-900/60 bg-red-950/30 p-3 text-xs text-red-200" role="alert">
          {error.message}
        </p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3">
        {isLoading && !data ? (
          <>
            {["Orchestrator", "Rule Engine", "Shadow AI"].map((t) => (
              <div
                key={t}
                className="h-36 animate-pulse rounded-lg border border-slate-800 bg-slate-900/40"
                aria-hidden
              />
            ))}
          </>
        ) : (
          <>
            <HealthCard
              title="Orchestrator"
              online={orchestrator?.online ?? false}
              latencyMs={orchestrator?.latency_ms ?? null}
              errorMessage={orchestrator?.error_message ?? null}
            />
            <HealthCard
              title="Rule Engine"
              online={ruleEngine?.online ?? false}
              latencyMs={ruleEngine?.latency_ms ?? null}
              errorMessage={
                ruleEngine && !ruleEngine.online
                  ? (ruleEngine.error_message ?? "503 Service Unavailable")
                  : null
              }
            />
            <HealthCard
              title="Shadow AI"
              online={shadowAi?.online ?? false}
              latencyMs={shadowAi?.latency_ms ?? null}
              errorMessage={shadowAi?.error_message ?? null}
            />
          </>
        )}
      </div>
    </section>
  );
}
