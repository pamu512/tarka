import { NextResponse } from "next/server";
import type { TimelineResponse } from "@/types/timeline";

/**
 * Proxy to the shadow sidecar ``GET /v1/transactions/{id}/timeline`` (cross-case analyst timeline).
 *
 * Server env: ``SHADOW_AGENT_URL`` (or ``NEXT_PUBLIC_SHADOW_AGENT_URL`` as fallback origin only),
 * and ``SHADOW_API_KEY`` for ``X-Shadow-Token``.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ transactionId: string }> },
) {
  const { transactionId: rawId } = await context.params;
  const transactionId = decodeURIComponent(rawId);
  if (!transactionId || transactionId.length > 512) {
    return NextResponse.json({ error: "invalid transaction id" }, { status: 400 });
  }

  const baseRaw =
    process.env.SHADOW_AGENT_URL?.trim() ??
    process.env.NEXT_PUBLIC_SHADOW_AGENT_URL?.trim() ??
    "";
  const base = baseRaw.replace(/\/$/, "");
  const token = process.env.SHADOW_API_KEY?.trim() ?? "";

  if (!base.length || !token.length) {
    const body: TimelineResponse = {
      entity_id: transactionId,
      events: [],
      alerts: [],
      warning:
        "Timeline unavailable: set SHADOW_AGENT_URL and SHADOW_API_KEY on the Next.js server.",
    };
    return NextResponse.json(body, { headers: { "Cache-Control": "no-store" } });
  }

  const url = `${base}/v1/transactions/${encodeURIComponent(transactionId)}/timeline`;
  const upstream = await fetch(url, {
    method: "GET",
    headers: { "X-Shadow-Token": token },
    cache: "no-store",
  });
  const payload = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }
  return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
}
