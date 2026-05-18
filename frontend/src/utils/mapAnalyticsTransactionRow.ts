import type { TransactionRow } from "@/domain/transactionRow";
import { normalizeDecisionSurface } from "@/domain/transactionRow";
import { extractHardwareSignalsFromPayload } from "@/domain/hardwareSignals";

function readMetaString(meta: Record<string, unknown> | null, key: string): string | null {
  if (!meta) return null;
  const v = meta[key];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function parseMetadata(raw: unknown): Record<string, unknown> | null {
  if (raw == null) return null;
  if (typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>;
  }
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      return null;
    }
  }
  return null;
}

/** Map orchestrator ``v_analytics_transactions`` row → live grid row. */
export function mapAnalyticsTransactionRow(raw: Record<string, unknown>): TransactionRow | null {
  const ts = typeof raw.ts === "string" ? raw.ts : raw.ts != null && typeof raw.ts === "object" && "toString" in raw.ts ? String(raw.ts) : null;
  const entityId = typeof raw.entity_id === "string" ? raw.entity_id : null;
  const amount = typeof raw.amount === "number" && Number.isFinite(raw.amount) ? raw.amount : null;
  const country = typeof raw.country === "string" ? raw.country : "—";
  if (!ts || !entityId || amount === null) return null;

  const meta = parseMetadata(raw.metadata);
  const traceId =
    readMetaString(meta, "trace_id") ??
    readMetaString(meta, "traceId") ??
    `tr-${entityId.slice(0, 8)}-${ts.slice(0, 10)}`;
  const decisionRaw =
    readMetaString(meta, "decision") ?? readMetaString(meta, "status") ?? readMetaString(meta, "surface");
  const channel =
    readMetaString(meta, "channel") ?? readMetaString(meta, "event_type") ?? country;
  const currency = readMetaString(meta, "currency") ?? "USD";
  const id = `${ts}|${entityId}|${amount}`;
  const hw = extractHardwareSignalsFromPayload(meta ?? {});

  return {
    id,
    timestamp: ts,
    traceId,
    entityId,
    amountCents: Math.round(amount * 100),
    currency,
    channel,
    status: normalizeDecisionSurface(decisionRaw ?? (amount >= 1000 ? "review" : "allow")),
    ...(Object.keys(hw).length > 0 ? { hardwareSignals: hw } : {}),
  };
}
