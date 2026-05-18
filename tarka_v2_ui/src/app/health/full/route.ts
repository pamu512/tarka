import { NextResponse } from "next/server";
import { probeHttpHealth } from "@/lib/probe-http-health";
import type { HealthFullResponse, HealthServiceSnapshot } from "@/types/health-full";

function syntheticLatency(seed: number): number {
  return Math.round(18 + (seed % 47) + (Math.sin(seed / 11) + 1) * 12);
}

function mockSnapshot(online: boolean, seed: number): HealthServiceSnapshot {
  if (!online) {
    return {
      online: false,
      latency_ms: null,
      error_message: "503 Service Unavailable",
    };
  }
  return {
    online: true,
    latency_ms: syntheticLatency(seed),
    error_message: null,
  };
}

/**
 * Local orchestrator aggregate for `/health/full`.
 *
 * - **Rule Engine**: set `RULE_ENGINE_HEALTH_URL` to the engine's `/health` (or root) URL.
 *   When that process is stopped, the probe fails and this route returns `503` in
 *   `rule_engine.error_message` with the card turning red on the next poll.
 * - **Optional kill-switch** (no backend needed): `RULE_ENGINE_FORCE_OFFLINE=1`
 * - **Shadow AI**: `SHADOW_AI_HEALTH_URL` optional; otherwise synthetic online latency.
 */
export async function GET() {
  const handlerStarted = performance.now();

  const ruleForce =
    typeof process.env.RULE_ENGINE_FORCE_OFFLINE === "string" &&
    process.env.RULE_ENGINE_FORCE_OFFLINE === "1";

  const ruleUrl = process.env.RULE_ENGINE_HEALTH_URL?.trim();
  let rule_engine: HealthServiceSnapshot;
  if (ruleForce) {
    rule_engine = {
      online: false,
      latency_ms: null,
      error_message: "503 Service Unavailable: RULE_ENGINE_FORCE_OFFLINE=1",
    };
  } else if (ruleUrl && ruleUrl.length > 0) {
    rule_engine = await probeHttpHealth(ruleUrl);
    if (!rule_engine.online && !rule_engine.error_message) {
      rule_engine = {
        ...rule_engine,
        error_message: "503 Service Unavailable",
      };
    }
  } else {
    rule_engine = mockSnapshot(true, Math.floor(Date.now() / 1000));
  }

  const shadowUrl = process.env.SHADOW_AI_HEALTH_URL?.trim();
  const shadow_ai =
    shadowUrl && shadowUrl.length > 0
      ? await probeHttpHealth(shadowUrl)
      : mockSnapshot(true, Math.floor(Date.now() / 1300) + 3);

  const orchestrator: HealthServiceSnapshot = {
    online: true,
    latency_ms: Math.max(1, Math.round(performance.now() - handlerStarted)),
    error_message: null,
  };

  const body: HealthFullResponse = {
    orchestrator,
    rule_engine,
    shadow_ai,
  };

  return NextResponse.json(body, { headers: { "Cache-Control": "no-store" } });
}
