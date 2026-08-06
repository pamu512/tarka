import { useCallback, useEffect, useMemo, useState } from "react";
import { bridge, type BridgeCaseStateChangePayload } from "../../../../api/client";
import {
  DISPOSITION_REASON_CODES,
  isDispositionReasonCode,
  isTerminalCaseStatus,
} from "../../../../config/dispositionReasonCodes";
import { useCaseWorkbench } from "../../../../context/CaseWorkbenchContext";
import { trackWorkbenchTask } from "../../../../workbench/workbenchTelemetry";

const BRIDGE_SECRET = (import.meta.env.VITE_BRIDGE_FIXTURE_SECRET as string | undefined)?.trim() ?? "dev-bridge-fixture";

export type BridgeConfirmResult = {
  reasonCode?: string;
};

type BridgeConfirmDialogProps = {
  onConfirm: (result: BridgeConfirmResult) => void | Promise<void>;
  onCancel: () => void;
};

/** E08 — adaptive confirm/cancel wired to bridge outbound schema validation. */
export function BridgeConfirmDialog({ onConfirm, onCancel }: BridgeConfirmDialogProps) {
  const {
    caseId,
    tenantId,
    caseData,
    bridgeConfirmOpen,
    setBridgeConfirmOpen,
    pendingStatusChange,
    setPendingStatusChange,
  } = useCaseWorkbench();
  const [schemaOk, setSchemaOk] = useState<boolean | null>(null);
  const [validating, setValidating] = useState(false);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [reasonCode, setReasonCode] = useState("");

  const terminal = isTerminalCaseStatus(pendingStatusChange);

  const payload = useMemo((): BridgeCaseStateChangePayload | null => {
    if (!caseData || !pendingStatusChange) return null;
    return {
      schema_id: "tarka.bridge.case_state_change/v1",
      event_id: `wb-${caseId}-${Date.now()}`,
      emitted_at: new Date().toISOString(),
      tenant_id: tenantId,
      case_id: caseId,
      previous_status: caseData.status,
      new_status: pendingStatusChange,
      previous_priority: caseData.priority,
      new_priority: caseData.priority,
      assigned_team: caseData.assigned_team ?? null,
      actor_id: "analyst-1",
      actor_role: "analyst",
      source: "case-api",
      platform: "api",
      labels: caseData.labels ?? [],
      metadata: {
        workbench: true,
        ...(reasonCode ? { disposition_reason_code: reasonCode } : {}),
      },
    };
  }, [caseData, caseId, tenantId, pendingStatusChange, reasonCode]);

  useEffect(() => {
    if (!bridgeConfirmOpen) {
      setReasonCode("");
      setSchemaOk(null);
      return;
    }
  }, [bridgeConfirmOpen]);

  useEffect(() => {
    if (!bridgeConfirmOpen || !payload) {
      setSchemaOk(null);
      return;
    }
    let cancelled = false;
    setValidating(true);
    void bridge
      .validateCaseStateChangeFixture(payload, BRIDGE_SECRET)
      .then(() => {
        if (!cancelled) setSchemaOk(true);
      })
      .catch(() => {
        if (!cancelled) setSchemaOk(false);
      })
      .finally(() => {
        if (!cancelled) setValidating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bridgeConfirmOpen, payload]);

  const close = useCallback(() => {
    setBridgeConfirmOpen(false);
    setPendingStatusChange(null);
    onCancel();
  }, [onCancel, setBridgeConfirmOpen, setPendingStatusChange]);

  const confirm = useCallback(async () => {
    if (confirmBusy) return;
    if (terminal && !isDispositionReasonCode(reasonCode)) return;
    setConfirmBusy(true);
    try {
      await onConfirm(terminal ? { reasonCode } : {});
      trackWorkbenchTask("bridge_status_confirm", {
        caseId,
        tenantId,
        detail: pendingStatusChange ?? undefined,
      });
      setBridgeConfirmOpen(false);
      setPendingStatusChange(null);
    } finally {
      setConfirmBusy(false);
    }
  }, [
    confirmBusy,
    onConfirm,
    caseId,
    tenantId,
    pendingStatusChange,
    setBridgeConfirmOpen,
    setPendingStatusChange,
    terminal,
    reasonCode,
  ]);

  if (!bridgeConfirmOpen || !payload) return null;

  const canConfirm = !confirmBusy && (!terminal || isDispositionReasonCode(reasonCode));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
      role="dialog"
      aria-modal
      aria-labelledby="bridge-confirm-title"
    >
      <div className="w-full max-w-md rounded-xl border border-surface-600 bg-surface-900 shadow-xl p-5 space-y-4">
        <h2 id="bridge-confirm-title" className="text-sm font-semibold text-gray-100">
          Confirm case status change
        </h2>
        <p className="text-sm text-gray-400">
          Move case from <span className="text-gray-200 capitalize">{payload.previous_status}</span> to{" "}
          <span className="text-gray-100 capitalize font-medium">{payload.new_status}</span>?
        </p>
        {terminal ? (
          <div>
            <label className="block text-xs text-gray-500 mb-1" htmlFor="disposition-reason-code">
              Disposition reason (required)
            </label>
            <select
              id="disposition-reason-code"
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
              className="w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
            >
              <option value="">Select reason…</option>
              {DISPOSITION_REASON_CODES.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label} ({r.yLabel})
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-gray-600">
              Joins calibration <span className="font-mono">y_label</span>; fraud reasons need a second actor
              (maker-checker).
            </p>
          </div>
        ) : null}
        <div className="rounded-lg border border-surface-700 bg-surface-950/50 p-3 text-[11px] font-mono text-gray-500 break-all">
          {validating ? (
            "Validating outbound webhook schema…"
          ) : schemaOk === true ? (
            <span className="text-emerald-400/90">✓ tarka.bridge.case_state_change/v1 fixture accepted</span>
          ) : schemaOk === false ? (
            <span className="text-amber-300/90">Schema validation skipped or unavailable — proceed with audited case-api update.</span>
          ) : null}
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={close}
            className="px-3 py-2 text-xs rounded-lg border border-surface-600 text-gray-300 hover:bg-surface-800"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canConfirm}
            onClick={() => void confirm()}
            className="px-3 py-2 text-xs rounded-lg bg-brand-600 text-white hover:bg-brand-500 disabled:opacity-45"
          >
            {confirmBusy ? "Applying…" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
