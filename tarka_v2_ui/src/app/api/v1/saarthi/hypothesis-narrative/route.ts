import { NextResponse } from "next/server";

import {
  buildHypothesisNarrativeUserContent,
  fallbackHypothesisNarrative,
  normalizeTwoSentenceNarrative,
  SAARTHI_HYPOTHESIS_NARRATIVE_SYSTEM,
} from "@/lib/saarthi/hypothesisNarrativePrompt";

const MAX_SCOUT_CHARS = 100_000;
const DEFAULT_MODEL = "gemini-1.5-pro";

type Body = {
  scout_result?: unknown;
  hypothesis_report?: unknown;
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

function pickReport(body: Body): Record<string, unknown> | null {
  if (body.hypothesis_report && typeof body.hypothesis_report === "object") {
    return body.hypothesis_report as Record<string, unknown>;
  }
  const scout = body.scout_result;
  if (scout && typeof scout === "object") {
    const reports = (scout as Record<string, unknown>).hypothesis_reports;
    if (Array.isArray(reports) && reports.length > 0 && typeof reports[0] === "object") {
      return reports[0] as Record<string, unknown>;
    }
  }
  return null;
}

function windowHoursElapsed(report: Record<string, unknown>): number | undefined {
  const start = report.window_start_utc;
  const end = report.window_end_utc;
  if (typeof start !== "string" || typeof end !== "string") return undefined;
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (Number.isNaN(a) || Number.isNaN(b)) return undefined;
  return Math.max((b - a) / 3_600_000, 1 / 60);
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  if (!("scout_result" in body) && !("hypothesis_report" in body)) {
    return NextResponse.json({ error: "missing scout_result or hypothesis_report" }, { status: 400 });
  }

  const report = pickReport(body);
  if (!report) {
    return NextResponse.json({ error: "no hypothesis report found in payload" }, { status: 400 });
  }

  const scoutPayload =
    body.scout_result && typeof body.scout_result === "object"
      ? (body.scout_result as Record<string, unknown>)
      : { hypothesis_reports: [report] };

  let scoutJson: string;
  try {
    scoutJson = JSON.stringify(scoutPayload);
  } catch {
    return NextResponse.json({ error: "scout payload is not JSON-serializable" }, { status: 400 });
  }

  if (scoutJson.length > MAX_SCOUT_CHARS) {
    return NextResponse.json({ error: "scout_result exceeds size limit" }, { status: 413 });
  }

  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) {
    const narrative = fallbackHypothesisNarrative({
      fingerprint_kind: String(report.fingerprint_kind ?? "canvas_hash"),
      fingerprint_value: String(report.fingerprint_value ?? ""),
      distinct_account_count: Number(report.distinct_account_count ?? 0),
      window_hours_elapsed: windowHoursElapsed(report),
    });
    return NextResponse.json(
      { narrative, attribution_engine: "fallback", sentence_count: 2, report_id: report.report_id ?? null },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  const model = typeof body.model === "string" && body.model.trim().length > 0 ? body.model.trim() : DEFAULT_MODEL;
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;

  const userText = buildHypothesisNarrativeUserContent(scoutJson);

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      systemInstruction: {
        parts: [{ text: SAARTHI_HYPOTHESIS_NARRATIVE_SYSTEM }],
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
    const narrative = fallbackHypothesisNarrative({
      fingerprint_kind: String(report.fingerprint_kind ?? "canvas_hash"),
      fingerprint_value: String(report.fingerprint_value ?? ""),
      distinct_account_count: Number(report.distinct_account_count ?? 0),
      window_hours_elapsed: windowHoursElapsed(report),
    });
    return NextResponse.json(
      {
        narrative,
        attribution_engine: "fallback",
        sentence_count: 2,
        report_id: report.report_id ?? null,
        gemini_error: rawText.slice(0, 500),
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  let geminiJson: unknown;
  try {
    geminiJson = JSON.parse(rawText) as unknown;
  } catch {
    return NextResponse.json({ error: "invalid Gemini response JSON" }, { status: 502 });
  }

  const rawNarrative = extractGeminiText(geminiJson);
  const normalized = normalizeTwoSentenceNarrative(rawNarrative);
  const attribution_engine = normalized ? "gemini" : "fallback";
  const narrative =
    normalized ??
    fallbackHypothesisNarrative({
      fingerprint_kind: String(report.fingerprint_kind ?? "canvas_hash"),
      fingerprint_value: String(report.fingerprint_value ?? ""),
      distinct_account_count: Number(report.distinct_account_count ?? 0),
      window_hours_elapsed: windowHoursElapsed(report),
    });

  return NextResponse.json(
    {
      narrative,
      attribution_engine,
      sentence_count: 2,
      report_id: report.report_id ?? null,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
