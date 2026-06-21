import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  orchestrator,
  type HilOverrideRow,
  type HilOverrideType,
} from "../../../../api/client";
import { DegradedModeBanner } from "../../../DegradedModeBanner";
import { useCaseWorkbench } from "../../../../context/CaseWorkbenchContext";
import { toUserFacingApiError } from "../../../../api/client";
import { trackPanelUsage, trackWorkbenchTask } from "../../../../workbench/workbenchTelemetry";

const OVERRIDE_TYPES: HilOverrideType[] = [
  "ALLOW_SEASONAL_SPIKE",
  "FORCE_BLOCK",
  "TEMPORARY_BASELINE_SHIFT",
];

const DEFAULT_ANALYST = "analyst-1";

/** E04 — entity HIL override controls (orchestrator ingress). */
export function HilOverridePanel() {
  const { caseId, tenantId, caseData, isPanelOpen, togglePanel } = useCaseWorkbench();
  const [rows, setRows] = useState<HilOverrideRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [overrideType, setOverrideType] = useState<HilOverrideType>("ALLOW_SEASONAL_SPIKE");
  const [scopeKey, setScopeKey] = useState("velocity_24h");
  const [rationale, setRationale] = useState("");

  const open = isPanelOpen("hil_overrides");
  const entityId = caseData?.entity_id ?? "";

  const reload = useCallback(async () => {
    if (!entityId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await orchestrator.listHilOverrides(entityId, tenantId);
      setRows(res.overrides ?? []);
    } catch (e) {
      setRows([]);
      setError(toUserFacingApiError(e, { subject: "HIL overrides", action: "list entity overrides" }));
    } finally {
      setLoading(false);
    }
  }, [entityId, tenantId]);

  useEffect(() => {
    if (!open || !entityId) return;
    trackPanelUsage("hil_overrides", true, { caseId, tenantId });
    void reload();
  }, [open, entityId, caseId, tenantId, reload]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!entityId || !rationale.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const idempotencyKey = `wb-${caseId.slice(0, 8)}-${Date.now()}`;
      await orchestrator.createHilOverride(entityId, {
        idempotency_key: idempotencyKey,
        tenant_id: tenantId,
        override_type: overrideType,
        scope_key: scopeKey.trim(),
        analyst_rationale: rationale.trim(),
        analyst_id: DEFAULT_ANALYST,
      });
      setRationale("");
      trackWorkbenchTask("hil_override_create", { caseId, tenantId, detail: overrideType });
      await reload();
    } catch (err) {
      setError(toUserFacingApiError(err, { subject: "HIL override", action: "create override" }));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open || !entityId) return null;

  return (
    <section aria-label="Entity HIL overrides" className="rounded-xl border border-surface-700 bg-surface-900/80 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">HIL overrides</h3>
        <button type="button" onClick={() => togglePanel("hil_overrides", false)} className="text-[11px] text-gray-500 hover:text-gray-300">
          Hide
        </button>
      </div>
      <DegradedModeBanner error={error} title="HIL override error" onDismiss={() => setError(null)} />
      {loading ? (
        <p className="text-sm text-gray-500">Loading active overrides…</p>
      ) : rows.length > 0 ? (
        <ul className="space-y-2 text-xs">
          {rows.map((r, i) => (
            <li key={`${r.scope_key}-${i}`} className="rounded-lg border border-surface-700/70 px-3 py-2">
              <span className="font-mono text-brand-300">{String(r.override_type)}</span>
              <span className="text-gray-500"> · </span>
              <span className="text-gray-300">{r.scope_key}</span>
              {r.expires_at ? (
                <span className="block text-gray-500 mt-0.5">expires {new Date(String(r.expires_at)).toLocaleString()}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-gray-500">No active overrides for this entity.</p>
      )}
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-2 border-t border-surface-700 pt-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="block text-[11px] text-gray-500">
            Override type
            <select
              value={overrideType}
              onChange={(e) => setOverrideType(e.target.value as HilOverrideType)}
              className="mt-1 w-full bg-surface-800 border border-surface-600 text-gray-300 text-xs rounded-lg px-2 py-1.5"
            >
              {OVERRIDE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-gray-500">
            Scope key
            <input
              value={scopeKey}
              onChange={(e) => setScopeKey(e.target.value)}
              className="mt-1 w-full bg-surface-800 border border-surface-600 text-gray-300 text-xs rounded-lg px-2 py-1.5 font-mono"
            />
          </label>
        </div>
        <label className="block text-[11px] text-gray-500">
          Analyst rationale
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={2}
            required
            className="mt-1 w-full bg-surface-800 border border-surface-600 text-gray-300 text-xs rounded-lg px-2 py-1.5"
            placeholder="Why this override is warranted…"
          />
        </label>
        <button
          type="submit"
          disabled={submitting || !rationale.trim()}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-brand-600/25 text-brand-200 border border-brand-500/35 hover:bg-brand-600/35 disabled:opacity-45"
        >
          {submitting ? "Submitting…" : "Apply override"}
        </button>
      </form>
    </section>
  );
}
