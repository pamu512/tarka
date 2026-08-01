import { useEffect, useState } from "react";
import { decisions } from "../api/v1/decisions";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

type Ingress = {
  request_signature_required?: boolean;
  integrity_soft_tags?: boolean;
  challenge_webhook_configured?: boolean;
  enforcement_webhook_configured?: boolean;
  replay_payload_ttl_seconds?: number;
  request_signature_max_skew_seconds?: number;
  request_signature_path_prefixes?: string[];
  docs?: string;
  decide_to_act_docs?: string;
};

export default function OpsIntegrity() {
  const [ingress, setIngress] = useState<Ingress | null>(null);
  const [platforms, setPlatforms] = useState<Record<string, Record<string, unknown>>>({});
  const [challengePolicies, setChallengePolicies] = useState<Array<Record<string, unknown>>>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [gov, posture, policies] = await Promise.all([
          decisions.governance(),
          decisions.policyPosture(),
          decisions.challengePolicies(),
        ]);
        const fromGov = (gov as { integrity_ingress?: Ingress }).integrity_ingress;
        const fromPosture = (
          posture as { integrity?: { ingress?: Ingress; matrix?: { platforms?: Record<string, Record<string, unknown>> } } }
        ).integrity;
        setIngress(fromPosture?.ingress ?? fromGov ?? null);
        setPlatforms(fromPosture?.matrix?.platforms ?? {});
        const list = (policies as { policies?: Array<Record<string, unknown>> }).policies;
        setChallengePolicies(Array.isArray(list) ? list : []);
      } catch (e) {
        setErr(toUserFacingError(e, { subject: "Integrity posture", action: "load integrity and challenge posture" }));
      }
    })();
  }, []);

  const platEntries = Object.entries(platforms);

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="compliance">Integrity &amp; challenge</PageTitle>
        <p className="text-sm text-gray-500">
          Replay / HMAC / pinning ingress flags + platform integrity matrix + challenge / enforcement webhook readiness.
        </p>
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

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm text-gray-300 grid gap-2 sm:grid-cols-2">
        <div>
          Request signature required:{" "}
          <span className="font-mono text-brand-300">{String(ingress?.request_signature_required ?? "—")}</span>
        </div>
        <div>
          Soft integrity tags:{" "}
          <span className="font-mono text-brand-300">{String(ingress?.integrity_soft_tags ?? "—")}</span>
        </div>
        <div>
          Challenge webhook configured:{" "}
          <span className="font-mono text-brand-300">{String(ingress?.challenge_webhook_configured ?? "—")}</span>
        </div>
        <div>
          Enforcement webhook configured:{" "}
          <span className="font-mono text-brand-300">{String(ingress?.enforcement_webhook_configured ?? "—")}</span>
        </div>
        <div>
          Replay payload TTL:{" "}
          <span className="font-mono text-brand-300">
            {ingress?.replay_payload_ttl_seconds != null ? `${ingress.replay_payload_ttl_seconds}s` : "—"}
          </span>
        </div>
        <div className="sm:col-span-2 text-xs text-gray-500">
          Paths:{" "}
          <span className="font-mono text-gray-400">
            {(ingress?.request_signature_path_prefixes ?? []).join(", ") || "/v1/decisions/evaluate"}
          </span>
          {ingress?.docs ? (
            <span className="ml-2">
              · <span className="font-mono">{ingress.docs}</span>
            </span>
          ) : null}
          {ingress?.decide_to_act_docs ? (
            <span className="ml-2">
              · <span className="font-mono">{ingress.decide_to_act_docs}</span>
            </span>
          ) : null}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <div className="bg-surface-800 px-3 py-2 text-xs font-medium text-gray-400">
          Integrity policy matrix (platforms)
        </div>
        <table className="min-w-full text-sm">
          <thead className="bg-surface-900 text-left text-gray-500">
            <tr>
              <th className="px-3 py-2">Platform</th>
              <th className="px-3 py-2">Attestation</th>
              <th className="px-3 py-2">Min confidence</th>
              <th className="px-3 py-2">High-confidence signals</th>
            </tr>
          </thead>
          <tbody>
            {platEntries.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                  No matrix loaded. See <span className="font-mono text-xs">GET /v1/ops/integrity-policy</span>.
                </td>
              </tr>
            ) : (
              platEntries.map(([name, row]) => (
                <tr key={name} className="border-t border-surface-700/80">
                  <td className="px-3 py-2 font-mono text-xs text-brand-300">{name}</td>
                  <td className="px-3 py-2 text-gray-400">{String(row.attestation_provider ?? "—")}</td>
                  <td className="px-3 py-2 tabular-nums text-gray-400">
                    {String(row.min_integrity_confidence_for_auto_action ?? "—")}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {Array.isArray(row.high_confidence_signals)
                      ? (row.high_confidence_signals as string[]).join(", ")
                      : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-surface-700 overflow-hidden">
        <div className="bg-surface-800 px-3 py-2 text-xs font-medium text-gray-400">
          Challenge policies (step_up → tenant webhook)
        </div>
        <table className="min-w-full text-sm">
          <thead className="bg-surface-900 text-left text-gray-500">
            <tr>
              <th className="px-3 py-2">Policy id</th>
              <th className="px-3 py-2">Version</th>
            </tr>
          </thead>
          <tbody>
            {challengePolicies.length === 0 ? (
              <tr>
                <td colSpan={2} className="px-3 py-6 text-center text-gray-500">
                  No challenge policies loaded.
                </td>
              </tr>
            ) : (
              challengePolicies.map((p, i) => (
                <tr key={String(p.policy_id ?? i)} className="border-t border-surface-700/80">
                  <td className="px-3 py-2 font-mono text-xs text-brand-300">{String(p.policy_id ?? "")}</td>
                  <td className="px-3 py-2 tabular-nums text-gray-400">{String(p.version ?? "—")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
