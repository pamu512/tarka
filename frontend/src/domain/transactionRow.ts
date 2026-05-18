/**
 * Live transaction row — decision surface maps fraud ops language to policy outcomes.
 */

import { extractHardwareSignalsFromPayload, type HardwareSignalMap } from "./hardwareSignals";

export type DecisionSurface = "Block" | "Allow" | "Challenge";

export interface TransactionRow {
  readonly id: string;
  readonly timestamp: string;
  readonly traceId: string;
  readonly entityId: string;
  readonly amountCents: number;
  readonly currency: string;
  readonly status: DecisionSurface;
  readonly channel: string;
  /** Flattened hardware / device instrumentation for visual diffing (optional). */
  readonly hardwareSignals?: HardwareSignalMap;
}

export function normalizeDecisionSurface(raw: string): DecisionSurface {
  const x = raw.trim().toLowerCase();
  if (x === "allow" || x === "approve") {
    return "Allow";
  }
  if (x === "block" || x === "deny") {
    return "Block";
  }
  if (x === "challenge" || x === "review") {
    return "Challenge";
  }
  return "Challenge";
}

function readString(obj: Record<string, unknown>, key: string): string | null {
  const v = obj[key];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function readNumber(obj: Record<string, unknown>, key: string): number | null {
  const v = obj[key];
  if (typeof v === "number" && Number.isFinite(v)) {
    return v;
  }
  if (typeof v === "string" && v.trim()) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Parses a server JSON payload into a row when possible (supports snake_case + camelCase).
 */
export function parseTransactionRowPayload(data: unknown): TransactionRow | null {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return null;
  }
  const o = data as Record<string, unknown>;
  const id = readString(o, "id") ?? readString(o, "transaction_id");
  const traceId = readString(o, "traceId") ?? readString(o, "trace_id");
  const entityId = readString(o, "entityId") ?? readString(o, "entity_id");
  const timestamp = readString(o, "timestamp") ?? readString(o, "created_at") ?? readString(o, "ts");
  const currency = readString(o, "currency") ?? "USD";
  const channel = readString(o, "channel") ?? readString(o, "event_type") ?? "—";
  const amountCents =
    readNumber(o, "amountCents") ??
    readNumber(o, "amount_cents") ??
    (readNumber(o, "amount") != null ? Math.round((readNumber(o, "amount") as number) * 100) : null);
  const statusRaw =
    readString(o, "status") ?? readString(o, "decision") ?? readString(o, "surface") ?? "Challenge";
  if (!id || !traceId || !entityId || !timestamp || amountCents === null) {
    return null;
  }
  const hw = extractHardwareSignalsFromPayload(o);
  return {
    id,
    traceId,
    entityId,
    timestamp,
    amountCents,
    currency,
    channel,
    status: normalizeDecisionSurface(statusRaw),
    ...(Object.keys(hw).length > 0 ? { hardwareSignals: hw } : {}),
  };
}
