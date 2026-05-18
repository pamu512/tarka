import { NextResponse } from "next/server";

import { normalizeBacktestBlockSeries } from "@/lib/hypothesis/backtestBlockSeries";

type Body = {
  rule?: Record<string, unknown>;
  suggested_rule?: Record<string, unknown>;
  series?: unknown;
  lookback_days?: number;
  duckdb_path?: string;
};

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  if (Array.isArray(body.series)) {
    return NextResponse.json(
      {
        lookback_days: body.lookback_days ?? 7,
        series: normalizeBacktestBlockSeries(body.series),
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  const rule = body.rule ?? body.suggested_rule;
  if (!rule || typeof rule !== "object") {
    return NextResponse.json({ error: "rule or series required" }, { status: 400 });
  }

  const shadowBase = process.env.SHADOW_AGENT_URL?.trim().replace(/\/$/, "");
  if (!shadowBase) {
    return NextResponse.json(
      { error: "SHADOW_AGENT_URL is not configured on the server" },
      { status: 503 },
    );
  }

  const token = process.env.SHADOW_API_TOKEN?.trim();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const upstream = await fetch(`${shadowBase}/v1/hypotheses/backtest-blocks`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      rule,
      lookback_days: body.lookback_days,
      duckdb_path: body.duckdb_path,
    }),
  });

  const rawText = await upstream.text();
  if (!upstream.ok) {
    return NextResponse.json(
      { error: "shadow backtest-blocks failed", detail: rawText.slice(0, 2000) },
      { status: 502 },
    );
  }

  let payload: { series?: unknown; lookback_days?: number };
  try {
    payload = JSON.parse(rawText) as { series?: unknown; lookback_days?: number };
  } catch {
    return NextResponse.json({ error: "invalid shadow response JSON" }, { status: 502 });
  }

  return NextResponse.json(
    {
      lookback_days: payload.lookback_days ?? body.lookback_days ?? 7,
      series: normalizeBacktestBlockSeries(payload.series),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
