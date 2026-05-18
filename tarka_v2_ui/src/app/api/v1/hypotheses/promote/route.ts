import { NextResponse } from "next/server";

type Body = {
  rule?: Record<string, unknown>;
  suggested_rule?: Record<string, unknown>;
};

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const rule = body.rule ?? body.suggested_rule;
  if (!rule || typeof rule !== "object") {
    return NextResponse.json({ error: "rule required" }, { status: 400 });
  }

  const ruleEngineBase = process.env.RULE_ENGINE_URL?.trim().replace(/\/$/, "");
  if (!ruleEngineBase) {
    return NextResponse.json(
      { error: "RULE_ENGINE_URL is not configured on the server" },
      { status: 503 },
    );
  }

  const upstream = await fetch(`${ruleEngineBase}/v1/rules/deploy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rules: [rule] }),
  });

  const rawText = await upstream.text();
  if (!upstream.ok) {
    return NextResponse.json(
      { error: "rule engine deploy failed", detail: rawText.slice(0, 2000) },
      { status: 502 },
    );
  }

  let payload: {
    version?: number;
    rule_count?: number;
    promotion_feedback?: Array<Record<string, unknown>>;
  };
  try {
    payload = JSON.parse(rawText) as typeof payload;
  } catch {
    return NextResponse.json({ error: "invalid rule engine response JSON" }, { status: 502 });
  }

  return NextResponse.json(
    {
      version: payload.version,
      rule_count: payload.rule_count,
      promotion_feedback: payload.promotion_feedback,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
