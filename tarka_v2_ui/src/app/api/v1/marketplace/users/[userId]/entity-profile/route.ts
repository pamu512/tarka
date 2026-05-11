import { NextResponse } from "next/server";
import { getOrchestratorBaseUrl } from "@/lib/orchestrator-base-url";

/**
 * BFF: ``GET /v1/marketplace/users/{userId}/entity-profile`` on the orchestrator (Entity Explorer).
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ userId: string }> },
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

  const { userId: raw } = await context.params;
  const userId = decodeURIComponent(raw || "").trim();
  if (!userId) {
    return NextResponse.json({ error: "missing userId" }, { status: 400 });
  }

  const url = `${base}/v1/marketplace/users/${encodeURIComponent(userId)}/entity-profile`;
  const upstream = await fetch(url, { method: "GET", cache: "no-store" });
  const payload = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }
  return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
}
