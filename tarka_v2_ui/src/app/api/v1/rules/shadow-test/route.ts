import { NextResponse } from "next/server";

/**
 * Forward ``POST /v1/rules/shadow-test`` to the orchestrator (draft rule replay vs. last 1k rows).
 *
 * Set ``TARKA_ORCHESTRATOR_BASE`` or ``NEXT_PUBLIC_ORCHESTRATOR_BASE_URL``.
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

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const url = `${base}/v1/rules/shadow-test`;
  const upstream = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }
  return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
}
