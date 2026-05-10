import { NextResponse } from "next/server";
import { pushAttackOutcome } from "@/lib/recent-audit-store";
import type { AuditRecentStatus } from "@/types/audit-recent";

function actionsToStatus(actions: string[] | undefined): AuditRecentStatus {
  if (!actions?.length) return "ALLOW";
  if (actions.includes("BLOCK")) return "BLOCK";
  if (actions.includes("FLAG")) return "FLAG";
  if (actions.includes("SHADOW_REVIEW")) return "SHADOW_REVIEW";
  if (actions.includes("ALLOW")) return "ALLOW";
  return "ALLOW";
}

/**
 * Dev helper: forward a TransactionSchema JSON body to the orchestrator ``POST /v1/ingest``
 * and mirror the rule outcome into the Live ticker (``recent-audit-store``).
 *
 * Set ``TARKA_ORCHESTRATOR_BASE`` or ``NEXT_PUBLIC_ORCHESTRATOR_BASE_URL`` to the orchestrator origin.
 */
export async function POST(req: Request) {
  const baseRaw =
    process.env.TARKA_ORCHESTRATOR_BASE ?? process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE_URL ?? "";
  const base = baseRaw.replace(/\/$/, "");
  if (!base.length) {
    return NextResponse.json(
      {
        error:
          "Set TARKA_ORCHESTRATOR_BASE or NEXT_PUBLIC_ORCHESTRATOR_BASE_URL to your orchestrator URL",
      },
      { status: 503 },
    );
  }

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const ingestUrl = `${base}/v1/ingest`;
  const upstream = await fetch(ingestUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const payload = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const ruleEngine = payload.rule_engine as { actions?: string[] } | undefined;
  const actions = ruleEngine?.actions;
  const uiStatus = actionsToStatus(actions);
  const tid =
    (typeof payload.transaction_id === "string" && payload.transaction_id) ||
    (typeof body.entity_id === "string" && body.entity_id) ||
    `txn_${Date.now()}`;
  const amount = typeof body.amount === "number" ? body.amount : 0;
  const amountCents = Math.round(amount * 100);

  pushAttackOutcome({
    timestamp: new Date().toISOString(),
    transaction_id: tid,
    amount_cents: amountCents,
    status: uiStatus,
  });

  return NextResponse.json({ ...payload, ui_status: uiStatus });
}
