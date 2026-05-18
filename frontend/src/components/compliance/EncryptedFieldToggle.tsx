import { useCallback, useId, useState, type ReactElement } from "react";

import { integrations } from "@/api/client";
import { useTenantEnvironment } from "@/context/TenantEnvironmentContext";
import { fingerprintPiiValue, maskPiiValue, type PiiFieldKind } from "@/utils/maskPii";

export type EncryptedFieldToggleProps = {
  value: string;
  kind?: PiiFieldKind;
  /** Stable path for audit, e.g. ``admin.users.email``. */
  fieldPath: string;
  contextType?: string;
  contextId?: string;
  tenantId?: string;
  className?: string;
  /** When true, audit events are still recorded but API failures are swallowed. */
  silentAuditErrors?: boolean;
};

/**
 * Masked PII display with reveal/hide control; each toggle writes an audit row (no plaintext stored server-side).
 */
export function EncryptedFieldToggle({
  value,
  kind = "generic",
  fieldPath,
  contextType = "ui",
  contextId,
  tenantId: tenantIdProp,
  className = "",
  silentAuditErrors = true,
}: EncryptedFieldToggleProps): ReactElement {
  const { tenantId: envTenant } = useTenantEnvironment();
  const tenantId = tenantIdProp ?? envTenant;
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const labelId = useId();

  const masked = maskPiiValue(value, kind);
  const display = revealed ? value : masked;

  const logToggle = useCallback(
    async (action: "reveal" | "hide") => {
      if (!value.trim()) return;
      setBusy(true);
      try {
        const fp = await fingerprintPiiValue(value);
        await integrations.piiFieldReveal({
          tenant_id: tenantId,
          action,
          field_kind: kind,
          field_path: fieldPath,
          context_type: contextType,
          context_id: contextId,
          value_fingerprint: fp,
          masked_preview: masked,
        });
        window.dispatchEvent(new CustomEvent("tarka:pii-reveal-audit"));
      } catch {
        if (!silentAuditErrors) throw new Error("PII reveal audit failed");
      } finally {
        setBusy(false);
      }
    },
    [value, tenantId, kind, fieldPath, contextType, contextId, masked, silentAuditErrors],
  );

  const onToggle = () => {
    if (busy || !value.trim()) return;
    const next = !revealed;
    void logToggle(next ? "reveal" : "hide").then(() => setRevealed(next));
  };

  if (!value.trim()) {
    return <span className={className}>—</span>;
  }

  return (
    <span className={`inline-flex items-center gap-1.5 min-w-0 ${className}`}>
      <span
        id={labelId}
        className={`font-mono truncate ${revealed ? "text-gray-200" : "text-gray-500 tracking-wide"}`}
        title={revealed ? undefined : "Masked — reveal to view"}
      >
        {display}
      </span>
      <button
        type="button"
        aria-labelledby={labelId}
        aria-pressed={revealed}
        disabled={busy}
        onClick={onToggle}
        className="shrink-0 rounded border border-surface-600 bg-surface-800/80 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-300 hover:bg-surface-700 disabled:opacity-50"
      >
        {busy ? "…" : revealed ? "Hide" : "Reveal"}
      </button>
    </span>
  );
}
