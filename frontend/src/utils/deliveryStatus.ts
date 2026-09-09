/** Thin emit/ACK glass. D9.4 may add retry/DLQ fields — do not fork a second log product. */

export type DeliveryChip = "emitted" | "acked" | "failed" | "not_configured";

export type ProductAckRef = {
  status?: string;
};

export type DeliveryStatusInput = {
  webhookConfigured: boolean;
  journalStatus?: string | null;
  journalReason?: string | null;
  productAck?: ProductAckRef | null;
  enforcementMode?: string | null;
};

export type DeliveryStatusView = {
  chip: DeliveryChip;
  label: string;
  hint: string;
};

const ADVISORY_HINT =
  "Advisory emit — Tarka did not block payout. Delivery status is emit/ACK glass, not an enforcement product suite.";

const PLANE_OFF_HINT =
  "Empty enforcement webhook URL — plane off, not configured. Not a fake ACK.";

const FAILED_STATUSES = new Set(["error", "non_2xx"]);

export function resolveDeliveryStatus(input: DeliveryStatusInput): DeliveryStatusView {
  const journal = (input.journalStatus || "").trim().toLowerCase();
  const reason = (input.journalReason || "").trim().toLowerCase();
  const planeOff =
    !input.webhookConfigured || journal === "skipped" || reason === "webhook_unset";

  if (planeOff) {
    return { chip: "not_configured", label: "not configured", hint: PLANE_OFF_HINT };
  }

  if (input.productAck && String(input.productAck.status || "").trim()) {
    return { chip: "acked", label: "acked", hint: ADVISORY_HINT };
  }

  if (FAILED_STATUSES.has(journal)) {
    return { chip: "failed", label: "failed", hint: ADVISORY_HINT };
  }

  return { chip: "emitted", label: "emitted", hint: ADVISORY_HINT };
}

export function journalRowForTrace(
  items: Array<Record<string, unknown>> | null | undefined,
  traceId: string,
  tenantId: string,
): Record<string, unknown> | null {
  const tid = traceId.trim();
  const ten = tenantId.trim();
  if (!tid || !ten || !items?.length) return null;
  for (let i = items.length - 1; i >= 0; i--) {
    const row = items[i];
    if (!row || typeof row !== "object") continue;
    if (String(row.trace_id || "") === tid && String(row.tenant_id || "") === ten) {
      return row;
    }
  }
  return null;
}
