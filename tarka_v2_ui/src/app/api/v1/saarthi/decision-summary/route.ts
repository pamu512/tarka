import { NextResponse } from "next/server";

import {
  buildDecisionSummaryUserContent,
  SAARTHI_DECISION_SUMMARY_SYSTEM,
} from "@/lib/saarthi/decisionSummaryPrompt";

const MAX_TRACE_CHARS = 100_000;
/** Gemini 1.5 Pro per Prompt 144 — override via JSON body.model if needed. */
const DEFAULT_MODEL = "gemini-1.5-pro";

type Body = {
  execution_trace?: unknown;
  model?: string;
};

function extractGeminiText(rawGeminiResponse: unknown): string {
  const g = rawGeminiResponse as Record<string, unknown>;
  const candidates = g.candidates;
  const first =
    Array.isArray(candidates) && candidates.length > 0 ? (candidates[0] as Record<string, unknown>) : null;
  const content = first?.content as Record<string, unknown> | undefined;
  const parts = content?.parts;
  if (!Array.isArray(parts) || parts.length === 0) return "";
  const part0 = parts[0] as { text?: string };
  return typeof part0.text === "string" ? part0.text.trim() : "";
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  if (!("execution_trace" in body)) {
    return NextResponse.json({ error: "missing execution_trace" }, { status: 400 });
  }

  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) {
    return NextResponse.json(
      { error: "GEMINI_API_KEY is not configured on the server" },
      { status: 503 },
    );
  }

  let traceJson: string;
  try {
    traceJson = JSON.stringify(body.execution_trace);
  } catch {
    return NextResponse.json({ error: "execution_trace is not JSON-serializable" }, { status: 400 });
  }

  if (traceJson.length > MAX_TRACE_CHARS) {
    return NextResponse.json({ error: "execution_trace exceeds size limit" }, { status: 413 });
  }

  const model = typeof body.model === "string" && body.model.trim().length > 0 ? body.model.trim() : DEFAULT_MODEL;
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;

  const userText = buildDecisionSummaryUserContent(traceJson);

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      systemInstruction: {
        parts: [{ text: SAARTHI_DECISION_SUMMARY_SYSTEM }],
      },
      contents: [
        {
          role: "user",
          parts: [{ text: userText }],
        },
      ],
      generationConfig: {
        temperature: 0.25,
        maxOutputTokens: 256,
      },
    }),
  });

  const rawText = await res.text();
  if (!res.ok) {
    return NextResponse.json(
      { error: "Gemini request failed", detail: rawText.slice(0, 2000) },
      { status: 502 },
    );
  }

  let geminiJson: unknown;
  try {
    geminiJson = JSON.parse(rawText) as unknown;
  } catch {
    return NextResponse.json({ error: "invalid Gemini response JSON" }, { status: 502 });
  }

  const summary = extractGeminiText(geminiJson);
  if (!summary) {
    return NextResponse.json(
      { error: "empty Gemini text response", raw_preview: rawText.slice(0, 800) },
      { status: 422 },
    );
  }

  const oneLine = summary.replace(/\s+/g, " ").trim();

  return NextResponse.json(
    { summary: oneLine },
    { headers: { "Cache-Control": "no-store" } },
  );
}
