import { useCallback, useEffect, useMemo, useState } from "react";
import { integrations } from "../../api/client";

export type VendorProvider = {
  id: string;
  name: string;
  category: string;
  type: string;
  required_config_fields?: string[];
  doc_url: string;
};

function isSecretConfigField(field: string): boolean {
  const k = field.toLowerCase();
  if (k === "username" || k === "user" || k === "email") return false;
  return (
    k.includes("password") ||
    k.includes("secret") ||
    k.includes("token") ||
    k.includes("api_key") ||
    k.endsWith("_key") ||
    k === "apikey" ||
    k === "key"
  );
}

const DEFAULT_SECRET_FIELDS = ["api_key", "password"] as const;

/** Renders saved credential hint only — never raw secrets (server sends masked values). */
function SavedCredentialHint({ label, masked }: { label: string; masked: string }) {
  if (!masked?.trim()) return null;
  return (
    <p className="text-[11px] text-gray-500 mt-1" data-testid={`saved-hint-${label}`}>
      Saved: <span className="font-mono text-gray-400 select-all">{masked}</span>
    </p>
  );
}

type Props = {
  open: boolean;
  onClose: () => void;
  provider: VendorProvider | null;
  tenantId: string;
  /** After a successful save, parent may refresh lists (must not merge raw secrets). */
  onSaved: () => void | Promise<void>;
};

/**
 * Secure OSINT / vendor integration credential modal.
 * - Secret inputs use `type="password"`.
 * - After save, masked hints come only from the configure response (no follow-up GET for secrets).
 */
export function VendorIntegrationConfigModal({ open, onClose, provider, tenantId, onSaved }: Props) {
  const [configDraft, setConfigDraft] = useState<Record<string, string>>({});
  /** Masked values only (e.g. ••••wxyz); never plaintext from API. */
  const [maskedHints, setMaskedHints] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fieldNames = useMemo(() => {
    const req = provider?.required_config_fields?.length
      ? [...provider.required_config_fields!]
      : ["api_key", "username", "password"];
    const set = new Set(req);
    for (const k of DEFAULT_SECRET_FIELDS) set.add(k);
    set.add("username");
    return Array.from(set);
  }, [provider]);

  const resetForClose = useCallback(() => {
    setConfigDraft({});
    setMaskedHints({});
    setError(null);
    setLoading(false);
    setSaving(false);
  }, []);

  useEffect(() => {
    if (!open || !provider) {
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      setConfigDraft({});
      try {
        const cfg = await integrations.getConfig(tenantId, provider.id);
        if (cancelled) return;
        setMaskedHints(cfg.masked_config ?? {});
      } catch {
        if (!cancelled) setMaskedHints({});
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, provider, tenantId]);

  const handleSave = async () => {
    if (!provider) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(configDraft)) {
        if (v != null && String(v).trim() !== "") payload[k] = v;
      }
      const res = await integrations.configure(tenantId, provider.id, payload);
      setMaskedHints(res.masked_config ?? {});
      setConfigDraft({});
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!open || !provider) return null;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="vendor-config-modal-title"
      onClick={() => {
        resetForClose();
        onClose();
      }}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-surface-600 bg-surface-900 shadow-xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-surface-700 px-4 py-3">
          <div>
            <h2 id="vendor-config-modal-title" className="text-sm font-semibold text-gray-100">
              Secure OSINT plugin hub
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">{provider.name}</p>
            <p className="text-[11px] text-gray-600 mt-1">
              API keys are sent only over HTTPS in production. Values are never shown in full after save.
            </p>
          </div>
          <button
            type="button"
            className="shrink-0 rounded-lg px-2 py-1 text-xs text-gray-400 hover:text-gray-200 hover:bg-surface-800"
            onClick={() => {
              resetForClose();
              onClose();
            }}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="p-4 space-y-4">
          {error && <div className="text-xs text-rose-300 bg-rose-950/40 border border-rose-800/50 rounded px-2 py-1.5">{error}</div>}

          {loading ? <div className="text-xs text-gray-500">Loading saved credential hints…</div> : null}

          <div className="space-y-3">
            {fieldNames.map((field) => {
              const secret = isSecretConfigField(field);
              const masked = maskedHints[field] ?? "";
              return (
                <div key={field}>
                  <label className="block text-xs font-medium text-gray-400 mb-1 capitalize">{field.replace(/_/g, " ")}</label>
                  {secret ? (
                    <input
                      type="password"
                      name={field}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={masked ? "Enter new value to rotate" : `Enter ${field}`}
                      value={configDraft[field] ?? ""}
                      onChange={(e) => setConfigDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                      className="w-full bg-surface-950 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
                    />
                  ) : (
                    <input
                      type="text"
                      name={field}
                      autoComplete="username"
                      spellCheck={false}
                      placeholder={`Enter ${field}`}
                      value={configDraft[field] ?? ""}
                      onChange={(e) => setConfigDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                      className="w-full bg-surface-950 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
                    />
                  )}
                  {masked ? <SavedCredentialHint label={field} masked={masked} /> : null}
                </div>
              );
            })}
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-surface-800">
            <button
              type="button"
              className="px-3 py-1.5 text-xs rounded-lg bg-surface-800 text-gray-300 hover:bg-surface-700"
              onClick={() => {
                resetForClose();
                onClose();
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={saving}
              className="px-3 py-1.5 text-xs rounded-lg bg-brand-600 text-white hover:bg-brand-500 disabled:opacity-40"
              onClick={() => void handleSave()}
            >
              {saving ? "Saving…" : "Save securely"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
