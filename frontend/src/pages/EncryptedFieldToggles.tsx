import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { integrations, type PiiFieldRevealAuditItem } from "../api/client";
import { EncryptedFieldToggle } from "../components/compliance/EncryptedFieldToggle";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const DEMO_FIELDS: Array<{
  id: string;
  label: string;
  value: string;
  kind: "email" | "phone" | "financial";
  fieldPath: string;
}> = [
  {
    id: "demo-email",
    label: "Customer email",
    value: "alex.chen@demo.tarka",
    kind: "email",
    fieldPath: "demo.customer.email",
  },
  {
    id: "demo-phone",
    label: "Mobile number",
    value: "+1 415 555 0199",
    kind: "phone",
    fieldPath: "demo.customer.phone",
  },
  {
    id: "demo-pan",
    label: "Payment identifier",
    value: "4111111111111111",
    kind: "financial",
    fieldPath: "demo.payment.pan",
  },
];

export default function EncryptedFieldToggles(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [audit, setAudit] = useState<PiiFieldRevealAuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useRegisterPageMeta({ title: "Encrypted field toggles", subtitle: "PII reveal audit" });

  const loadAudit = useCallback(async () => {
    try {
      const res = await integrations.piiFieldRevealAudit(tenantId, 50);
      setAudit(res.items);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "PII reveal audit", action: "load audit trail" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void loadAudit();
  }, [loadAudit]);

  useEffect(() => {
    const onReveal = () => {
      void loadAudit();
    };
    window.addEventListener("tarka:pii-reveal-audit", onReveal);
    return () => window.removeEventListener("tarka:pii-reveal-audit", onReveal);
  }, [loadAudit]);

  return (
    <div className="p-6 flex flex-col gap-6 max-w-4xl animate-fade-in">
      <div>
        <PageTitle module="compliance">Encrypted field toggles</PageTitle>
        <p className="text-sm text-gray-500 mt-2 leading-relaxed">
          Sensitive PII (emails, phones, payment identifiers) renders <strong className="text-gray-400">masked</strong> by
          default. Each <strong className="text-brand-300">Reveal</strong> or <strong className="text-brand-300">Hide</strong>{" "}
          click writes an immutable audit row — plaintext is never persisted server-side, only a SHA-256 fingerprint and
          masked preview.
        </p>
        <p className="text-[11px] text-gray-600 mt-2 font-mono">POST /api/ingress/v1/compliance/pii-field-reveal</p>
      </div>

      <section className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-200">Demo fields</h2>
        <ul className="space-y-3">
          {DEMO_FIELDS.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="text-gray-500 w-36 shrink-0">{f.label}</span>
              <EncryptedFieldToggle
                value={f.value}
                kind={f.kind}
                fieldPath={f.fieldPath}
                contextType="encrypted_field_demo"
                contextId={f.id}
                tenantId={tenantId}
                className="flex-1 min-w-[200px]"
                silentAuditErrors={false}
              />
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-gray-600">
          Wired in production UI on{" "}
          <Link to="/admin" className="text-brand-400 hover:text-brand-300">
            Admin → user emails
          </Link>{" "}
          and OSINT enrichment results.
        </p>
      </section>

      <section className="rounded-xl border border-surface-700 bg-surface-900/60 overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-700 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-gray-200">Reveal audit trail</h2>
          <button
            type="button"
            onClick={() => void loadAudit()}
            className="text-xs text-brand-400 hover:text-brand-300"
          >
            Refresh
          </button>
        </div>
        {error ? (
          <div className="px-4 py-3 text-sm text-rose-200">
            {error}
            <SupportIdHint className="mt-2" />
          </div>
        ) : loading ? (
          <p className="px-4 py-6 text-sm text-gray-500">Loading audit…</p>
        ) : audit.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-500">No reveal/hide events yet — toggle a field above.</p>
        ) : (
          <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-900 text-gray-500 uppercase tracking-wide">
                <tr className="border-b border-surface-700">
                  <th className="text-left px-3 py-2">Time</th>
                  <th className="text-left px-3 py-2">Action</th>
                  <th className="text-left px-3 py-2">Field</th>
                  <th className="text-left px-3 py-2">Preview</th>
                  <th className="text-left px-3 py-2">Actor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-800 text-gray-300">
                {audit.map((row) => (
                  <tr key={row.id}>
                    <td className="px-3 py-2 font-mono whitespace-nowrap">
                      {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`uppercase text-[10px] font-semibold ${
                          row.action === "reveal" ? "text-amber-300" : "text-gray-500"
                        }`}
                      >
                        {row.action}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px]">{row.field_path}</td>
                    <td className="px-3 py-2 font-mono text-gray-500">{row.masked_preview}</td>
                    <td className="px-3 py-2 text-gray-500">{row.actor_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
