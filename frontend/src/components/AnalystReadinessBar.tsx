import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  decisions,
  type DecisionApiSloResponse,
  type EvaluationPostureResponse,
} from "../api/client";

const DEP_LABELS: Record<string, string> = {
  redis: "Redis (cache / tags)",
  graph_service_configured: "Graph service URL",
  feature_service_configured: "Feature service URL",
  ml_scoring_configured: "ML scoring URL",
  nats_configured: "NATS / streaming",
  opa_configured: "OPA policy URL",
};

function remediation(
  depId: string,
  tier: string,
): { text: string; to?: string; href?: string } {
  const common = { to: "/help#readiness" as const, text: "Readiness & remediation (Help)" };
  switch (depId) {
    case "redis":
      return { ...common, text: "Verify Redis URL and decision-api health (Help → Readiness)" };
    case "graph_service_configured":
      return tier === "community"
        ? { ...common, text: "Optional in Community tier; enable graph profile for Pro stack" }
        : { ...common, text: "Set GRAPH_SERVICE_URL and start graph profile (deployment guide)" };
    case "feature_service_configured":
    case "ml_scoring_configured":
      return { ...common, text: "Enable ML profile or set service URLs in environment" };
    case "nats_configured":
      return { ...common, text: "Start streaming profile or set NATS_URL for event fan-out" };
    case "opa_configured":
      return { ...common, text: "Configure OPA_URL if policy hooks are required" };
    default:
      return common;
  }
}

/**
 * OSS #36 / #51 — analyst mode strip, compliance/degraded alerts, and expandable dependency matrix
 * with remediation links (pairs with decision-api evaluation-posture + SLO).
 */
export function AnalystReadinessBar() {
  const [posture, setPosture] = useState<EvaluationPostureResponse | null>(null);
  const [slo, setSlo] = useState<DecisionApiSloResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [p, s] = await Promise.all([decisions.evaluationPosture(), decisions.slo()]);
        if (!cancelled) {
          setPosture(p);
          setSlo(s);
          setErr(null);
        }
      } catch (e) {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : "unavailable");
          setPosture(null);
          setSlo(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const redisDown = slo?.current?.redis_connected === false;
  const natsDown = slo?.current?.nats_connected === false;

  const runtimeDegraded = useMemo(
    () => Boolean(redisDown || natsDown),
    [redisDown, natsDown],
  );

  if (err) {
    return (
      <div
        className="shrink-0 border-b border-amber-900/50 bg-amber-950/40 px-4 py-2 text-xs text-amber-100"
        role="status"
      >
        <span className="font-medium">Analyst readiness:</span> could not load decision-api signals ({err}). Check API
        proxy and credentials.
      </div>
    );
  }

  if (!posture) {
    return (
      <div className="shrink-0 border-b border-surface-800 bg-surface-900/40 px-4 py-1.5 text-[11px] text-gray-500">
        Loading analyst readiness…
      </div>
    );
  }

  const modeLabel =
    posture.evaluation_mode === "compliance" ? "Compliance evaluation" : "Detection evaluation";
  const tier = posture.deployment_tier === "community" ? "community" : "pro";
  const tierLabel = posture.deployment_tier === "community" ? "Community-shaped" : "Pro-shaped";
  const trpRaw = posture.tenant_reliability_profile ?? "balanced";
  const trp =
    trpRaw === "strict" || trpRaw === "balanced" || trpRaw === "permissive" ? trpRaw : "balanced";
  const trpLabel =
    trp === "strict" ? "Strict reliability" : trp === "permissive" ? "Permissive reliability" : "Balanced reliability";
  const complianceDegraded = posture.compliance_degraded === true;
  const reasons = (posture.compliance_degraded_reasons ?? []).join(", ");
  const showAlert = complianceDegraded || runtimeDegraded;

  return (
    <div className="shrink-0 border-b border-surface-800 bg-surface-900/60">
      {showAlert ? (
        <div
          className={`px-4 py-2 text-xs border-b ${
            complianceDegraded
              ? "text-amber-50 bg-amber-950/50 border-amber-900/40"
              : "text-rose-50 bg-rose-950/40 border-rose-900/40"
          }`}
          role="alert"
        >
          {complianceDegraded ? (
            <>
              <span className="font-semibold">Compliance prerequisites degraded.</span>{" "}
              {reasons ? <span className="text-amber-100/90">({reasons}) </span> : null}
            </>
          ) : (
            <>
              <span className="font-semibold">Runtime degraded.</span>{" "}
              {redisDown ? <span className="text-rose-100/90">Redis disconnected </span> : null}
              {natsDown ? <span className="text-rose-100/90">NATS disconnected </span> : null}
            </>
          )}
          <a
            href={posture.runbook_url}
            target="_blank"
            rel="noreferrer"
            className="text-brand-300 hover:text-brand-200 underline ml-1"
          >
            Deployment profiles
          </a>
          {" · "}
          <Link to="/help#readiness" className="text-brand-300 hover:text-brand-200 underline">
            Remediation
          </Link>
        </div>
      ) : null}

      <div className="px-4 py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400 border-b border-surface-800/80">
        <span className="text-gray-500 font-medium uppercase tracking-wide text-[10px]">Analyst workspace</span>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
            posture.evaluation_mode === "compliance"
              ? "bg-indigo-600/30 text-indigo-100 border border-indigo-500/40"
              : "bg-surface-700 text-gray-200 border border-surface-600"
          }`}
        >
          {modeLabel}
        </span>
        <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-surface-800 text-gray-300 border border-surface-600">
          {tierLabel}
        </span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-surface-800/90 text-gray-300 border border-surface-600"
          title="TARKA_TENANT_RELIABILITY_PROFILE (decision-api)"
        >
          {trpLabel}
        </span>
        {slo?.current?.redis_connected != null ? (
          <span className={slo.current.redis_connected ? "text-emerald-400/90" : "text-rose-400"}>
            Redis: {slo.current.redis_connected ? "up" : "down"}
          </span>
        ) : null}
        {slo?.current?.nats_connected != null ? (
          <span className={slo.current.nats_connected ? "text-emerald-400/90" : "text-gray-500"}>
            NATS: {slo.current.nats_connected ? "up" : "n/a"}
          </span>
        ) : null}
        <span className="ml-auto text-gray-600">
          Posture: <span className="text-gray-300">{posture.compliance_posture}</span>
        </span>
      </div>

      <details className="group px-4 py-2 text-[11px] text-gray-400">
        <summary className="cursor-pointer list-none flex items-center gap-2 text-gray-300 hover:text-gray-100 select-none">
          <span className="text-gray-500 group-open:text-brand-300">▸</span>
          <span className="font-medium">Dependency &amp; typology status</span>
          <span className="text-gray-600">(expand)</span>
        </summary>
        <div className="mt-3 space-y-3 pl-1">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-[11px]">
            <span>
              <span className="text-gray-500">Typologies:</span>{" "}
              <span className="tabular-nums text-gray-200">{posture.typology_count}</span>
            </span>
            <span>
              <span className="text-gray-500">Predicate registry:</span>{" "}
              <span className="tabular-nums text-gray-200">v{posture.predicate_registry_version}</span>
              {posture.predicate_registry_pin_match ? (
                <span className="text-emerald-400/90 ml-1">pin ok</span>
              ) : (
                <span className="text-amber-400/90 ml-1">pin mismatch</span>
              )}
            </span>
            {posture.last_rules_reload_at ? (
              <span className="sm:col-span-2">
                <span className="text-gray-500">Rules / typology materialized:</span>{" "}
                <span className="text-gray-300 font-mono">{posture.last_rules_reload_at}</span>
              </span>
            ) : null}
          </div>

          <div className="overflow-x-auto rounded-lg border border-surface-700/80">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-surface-800/80 text-gray-500">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Dependency</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Remediation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-800">
                {posture.dependencies.map((d) => {
                  const label = DEP_LABELS[d.id] ?? d.id;
                  const rem = remediation(d.id, tier);
                  return (
                    <tr key={d.id} className="text-gray-300">
                      <td className="px-2 py-1.5">{label}</td>
                      <td className="px-2 py-1.5">
                        {d.ok ? (
                          <span className="text-emerald-400/90">ok</span>
                        ) : (
                          <span className="text-amber-400/90">not configured</span>
                        )}
                        {d.detail ? (
                          <span className="text-gray-600 ml-1">({d.detail})</span>
                        ) : null}
                      </td>
                      <td className="px-2 py-1.5">
                        {rem.to ? (
                          <Link to={rem.to} className="text-brand-400 hover:text-brand-300 underline">
                            {rem.text}
                          </Link>
                        ) : rem.href ? (
                          <a href={rem.href} className="text-brand-400 hover:text-brand-300 underline" target="_blank" rel="noreferrer">
                            {rem.text}
                          </a>
                        ) : (
                          <span className="text-gray-500">{rem.text}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </details>
    </div>
  );
}
