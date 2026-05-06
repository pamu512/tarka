import type { DecisionSurface, TransactionRow } from "./transactionRow";

const STATUSES: readonly DecisionSurface[] = ["Block", "Allow", "Challenge"];

const CHANNELS = ["ach", "card", "wire", "rtp", "crypto", "wallet"] as const;

/** Monotonic ISO timestamps descending by row index (newest first when rendered top-down). */
export function buildTransactionSeed(count: number, nowMs: number = Date.now()): TransactionRow[] {
  const rows: TransactionRow[] = new Array(count);
  for (let i = 0; i < count; i++) {
    const ts = new Date(nowMs - i * 750).toISOString();
    rows[i] = {
      id: `tx-${i}`,
      timestamp: ts,
      traceId: `tr-${(i * 7919) % 900_000}`,
      entityId: `ent-${(i * 104729) % 250_000}`,
      amountCents: ((i * 9973) % 500_000) + 1,
      currency: "USD",
      status: STATUSES[i % 3]!,
      channel: CHANNELS[i % CHANNELS.length]!,
    };
  }
  return rows;
}
