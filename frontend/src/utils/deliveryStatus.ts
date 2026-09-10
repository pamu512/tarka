/** G4.4 emit/ACK glass, extended in D9.4 with retry/DLQ. Same strip — not a second log product. */

export type DeliveryChip =
  | "emitted"
  | "acked"
  | "failed"
  | "not_configured"
  | "retrying"
  | "dead_lettered";

export type ProductAckRef = {
  status?: string;
};

export type DeliveryStatusInput = {
  webhookConfigured: boolean;
  journalStatus?: string | null;
  journalReason?: string | null;
  productAck?: ProductAckRef | null;
  enforcementMode?: string | null;
  /** D9.3 GET /v1/enforcement/deliveries last_status. Journal HTTP 2xx is emitted, not acked. */
  lastStatus?: string | null;
};

export type DeliveryStatusView = {
  chip: DeliveryChip;
  label: string;
  hint: string;
};

const HELP = "Delivery reliability is not an enforcement SKU suite.";

const ADVISORY_HINT = `Advisory emit — ${HELP}`;

const RETRY_HINT = `Advisory emit — webhook retry in flight. ${HELP}`;

const DLQ_HINT = `Advisory emit — delivery dead-lettered after retries. Not Demote. ${HELP}`;

const PLANE_OFF_HINT =
  "Empty enforcement webhook URL — plane off, not configured. Not a fake ACK.";

const FAILED_STATUSES = new Set(["error", "non_2xx", "failed"]);

export function resolveDeliveryStatus(input: DeliveryStatusInput): DeliveryStatusView {
  const last = (input.lastStatus || "").trim().toLowerCase();
  const journal = (input.journalStatus || "").trim().toLowerCase();
  const reason = (input.journalReason || "").trim().toLowerCase();
  const planeOff =
    !input.webhookConfigured ||
    last === "not_configured" ||
    last === "skipped" ||
    journal === "skipped" ||
    reason === "webhook_unset";

  if (planeOff) {
    return { chip: "not_configured", label: "not configured", hint: PLANE_OFF_HINT };
  }

  if (last === "retrying" || journal === "retrying") {
    return { chip: "retrying", label: "retrying", hint: RETRY_HINT };
  }
  if (last === "dead_lettered" || journal === "dead_lettered") {
    return { chip: "dead_lettered", label: "dead lettered", hint: DLQ_HINT };
  }

  // D9.3 last_status=acked is product ACK. Journal status=acked is sink HTTP 2xx → emitted.
  if (last === "acked" || (input.productAck && String(input.productAck.status || "").trim())) {
    return { chip: "acked", label: "acked", hint: ADVISORY_HINT };
  }

  if (FAILED_STATUSES.has(last) || FAILED_STATUSES.has(journal)) {
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

export type DeliveryQueryRow = {
  trace_id?: string;
  tenant_id?: string;
  last_status?: string;
  last_error?: string | null;
};

export function deliveryQueryRowForTrace(
  items: DeliveryQueryRow[] | null | undefined,
  traceId: string,
  tenantId: string,
): DeliveryQueryRow | null {
  const tid = traceId.trim();
  const ten = tenantId.trim();
  if (!tid || !ten || !items?.length) return null;
  for (const row of items) {
    if (!row || typeof row !== "object") continue;
    if (String(row.trace_id || "") === tid && String(row.tenant_id || "") === ten) {
      return row;
    }
  }
  return null;
}

export const DELIVERY_RELIABILITY_HELP = HELP;
