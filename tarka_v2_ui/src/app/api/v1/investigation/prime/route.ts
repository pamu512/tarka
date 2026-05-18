import { NextResponse } from "next/server";
import { getOrchestratorBaseUrl } from "@/lib/orchestrator-base-url";

/**
 * Forward multipart uploads to the orchestrator ``POST /v1/investigation/prime`` for analyst priming.
 *
 * Set ``TARKA_ORCHESTRATOR_BASE`` or ``NEXT_PUBLIC_ORCHESTRATOR_BASE_URL`` to the orchestrator origin.
 */
export async function POST(req: Request) {
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

  let incoming: FormData;
  try {
    incoming = await req.formData();
  } catch {
    return NextResponse.json({ error: "Expected multipart form-data body" }, { status: 400 });
  }

  const file = incoming.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "Missing file field" }, { status: 400 });
  }

  const out = new FormData();
  out.append("file", file, file.name || "upload");

  const primeUrl = `${base}/v1/investigation/prime`;
  const upstream = await fetch(primeUrl, { method: "POST", body: out });
  const payload = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }
  return NextResponse.json(payload);
}
