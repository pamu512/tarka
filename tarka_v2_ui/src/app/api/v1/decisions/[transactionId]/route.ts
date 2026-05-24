import { NextResponse } from "next/server";
import { getOrchestratorBaseUrl } from "@config/env";
import { normalizeDecisionDetailResponse } from "@/lib/decision-detail-response";

/**
 * BFF: ``GET /v1/decisions/{transactionId}`` on the orchestrator (real audit + Shadow detail).
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ transactionId: string }> },
) {
  const base = getOrchestratorBaseUrl();
  if (!base.length) {
    return NextResponse.json(
      {
        error:
          "Set TARKA_ORCHESTRATOR_BASE or NEXT_PUBLIC_ORCHESTRATOR_BASE_URL to your orchestrator URL",
      },
      { status: 503 },
    );
  }

  const { transactionId: rawId } = await context.params;
  const transactionId = decodeURIComponent(rawId || "").trim();

  if (!transactionId || transactionId.length > 512) {
    return NextResponse.json({ error: "invalid transaction id" }, { status: 400 });
  }

  const url = `${base}/v1/decisions/${encodeURIComponent(transactionId)}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, { method: "GET", cache: "no-store" });
  } catch {
    return NextResponse.json({ error: "orchestrator unreachable" }, { status: 502 });
  }

  const payload = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;

  if (upstream.status === 404) {
    return NextResponse.json(
      payload.error ? payload : { error: "decision_not_found", transaction_id: transactionId },
      { status: 404 },
    );
  }

  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const normalized = normalizeDecisionDetailResponse(payload);
  if (!normalized) {
    return NextResponse.json(
      { error: "invalid_decision_detail_shape", transaction_id: transactionId },
      { status: 502 },
    );
  }

  return NextResponse.json(normalized, { headers: { "Cache-Control": "no-store" } });
}
