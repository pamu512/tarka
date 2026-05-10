import { pushAttackOutcome } from "@/lib/recent-audit-store";
import type { AuditRecentItem, AuditRecentStatus } from "@/types/audit-recent";

const STATUSES: readonly AuditRecentStatus[] = [
  "BLOCK",
  "FLAG",
  "SHADOW_REVIEW",
  "ALLOW",
] as const;

function buildAttackItem(patternIndex: number, batchId: number): AuditRecentItem {
  const now = Date.now();
  return {
    timestamp: new Date(now).toISOString(),
    transaction_id: `txn_attack_${batchId}_p${patternIndex}_${Math.random().toString(36).slice(2, 10)}`,
    amount_cents: 25_000 + patternIndex * 4_321,
    status: STATUSES[patternIndex % STATUSES.length],
  };
}

export async function POST() {
  const encoder = new TextEncoder();
  const batchId = Date.now();

  const stream = new ReadableStream({
    async start(controller) {
      try {
        for (let patternIndex = 0; patternIndex < 5; patternIndex++) {
          await new Promise<void>((resolve) => {
            setTimeout(resolve, 420);
          });
          const item = buildAttackItem(patternIndex, batchId);
          pushAttackOutcome(item);
          const payload = JSON.stringify({
            pattern_index: patternIndex,
            total: 5,
            item,
          });
          controller.enqueue(encoder.encode(`${payload}\n`));
        }
        controller.close();
      } catch (err) {
        controller.error(err);
      }
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
