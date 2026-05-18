import { NextResponse } from "next/server";

import { buildSaarthiAstUserContent, SAARTHI_AST_SYSTEM_INSTRUCTION } from "@/lib/ast-translator/saarthiAstPrompt";
import { parseGeminiAstTranslatorText } from "@/lib/ast-translator/validateAstTranslatorPayload";

const MAX_TRACE_CHARS = 100_000;
const DEFAULT_MODEL = "gemini-2.0-flash";

type Body = {
  trace?: unknown;
  model?: string;
};

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  if (!("trace" in body)) {
    return NextResponse.json({ error: "missing trace" }, { status: 400 });
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
    traceJson = JSON.stringify(body.trace);

  } catch {
    return NextResponse.json({ error: "trace is not JSON-serializable" }, { status: 400 });
  }

  if (traceJson.length > MAX_TRACE_CHARS) {
    return NextResponse.json({ error: "trace exceeds size limit" }, { status: 413 });
  }

  const model = typeof body.model === "string" && body.model.trim().length > 0 ? body.model.trim() : DEFAULT_MODEL;
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;

  const userText = buildSaarthiAstUserContent(traceJson);

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      systemInstruction: {
        parts: [{ text: SAARTHI_AST_SYSTEM_INSTRUCTION }],
      },
      contents: [
        {
          role: "user",
          parts: [{ text: userText }],
        },
      ],
      generationConfig: {
        temperature: 0.15,
        maxOutputTokens: 512,
        responseMimeType: "application/json",
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

  const g = geminiJson as Record<string, unknown>;
  const candidates = g.candidates;
  const first =
    Array.isArray(candidates) && candidates.length > 0 ? (candidates[0] as Record<string, unknown>) : null;
  const content = first?.content as Record<string, unknown> | undefined;
  const parts = content?.parts;
  const text =
    Array.isArray(parts) && parts.length > 0 && typeof (parts[0] as { text?: string }).text === "string"
      ? String((parts[0] as { text: string }).text)
      : "";

  const parsed = parseGeminiAstTranslatorText(text);
  if (!parsed) {
    return NextResponse.json(
      {
        error: "model output did not match AstTranslator schema",
        raw_preview: text.slice(0, 800),
      },
      { status: 422 },
    );
  }

  return NextResponse.json(parsed, {
    headers: { "Cache-Control": "no-store" },
  });
}
