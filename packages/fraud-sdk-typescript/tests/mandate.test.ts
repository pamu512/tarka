import { describe, expect, it, vi } from "vitest";

import { applyAgentMandate, DecisionClient, EventIngestClient, mandateExpired } from "../src/index.js";

const NOW = Date.parse("2026-01-01T00:00:00Z");

describe("applyAgentMandate", () => {
  it("leaves actor_kind off the body when it is absent", () => {
    const body = applyAgentMandate(
      { tenant_id: "t", event_type: "login", entity_id: "u", payload: {} },
      NOW,
    );
    expect(body.actor_kind).toBeUndefined();
    expect(body.score).toBeUndefined();
    expect(body.decision).toBeUndefined();
    expect("actor_kind" in body).toBe(false);
  });

  it("marks past and unparseable expiry out of mandate and drops empty caps", () => {
    const past = applyAgentMandate(
      {
        actor_kind: "agent",
        mandate_caps: {},
        mandate_expires_at: "2020-01-01T00:00:00Z",
      },
      NOW,
    );
    expect(past.actor_kind).toBe("agent");
    expect(past.mandate_caps).toBeUndefined();
    expect(past.mandate_expired).toBe(true);
    expect(past.score).toBeUndefined();

    const bad = applyAgentMandate(
      {
        actor_kind: "agent",
        mandate_caps: { spend_limit: 1 },
        mandate_expires_at: "not-a-date",
      },
      NOW,
    );
    expect(bad.mandate_expired).toBe(true);
    expect(mandateExpired("not-a-date", NOW)).toBe(true);
  });

  it("treats epoch milliseconds and Agent case as the same mandate", () => {
    const pastMs = Date.parse("2020-01-01T00:00:00Z");
    const futureMs = Date.parse("2099-01-01T00:00:00Z");
    const past = applyAgentMandate(
      { actor_kind: "AGENT", mandate_caps: { spend_limit: 1 }, mandate_expires_at: pastMs },
      NOW,
    );
    expect(past.actor_kind).toBe("agent");
    expect(past.mandate_expired).toBe(true);
    expect(past.score).toBeUndefined();
    const future = applyAgentMandate(
      { actor_kind: "Agent", mandate_caps: { spend_limit: 1 }, mandate_expires_at: futureMs },
      NOW,
    );
    expect(future.actor_kind).toBe("agent");
    expect(future.mandate_expired).toBeUndefined();
    expect(mandateExpired(pastMs / 1000, NOW)).toBe(true);
    expect(mandateExpired(futureMs, NOW)).toBe(false);
  });

  it("keeps caps and omits mandate_expired while the timestamp is in the future", () => {
    const body = applyAgentMandate(
      {
        actor_kind: "agent",
        mandate_caps: { spend_limit: 10 },
        mandate_expires_at: "2099-01-01T00:00:00Z",
      },
      NOW,
    );
    expect(body.mandate_caps).toEqual({ spend_limit: 10 });
    expect(body.mandate_expired).toBeUndefined();
  });
});

describe("DecisionClient and EventIngestClient emit", () => {
  it("posts agent mandate fields and leaves an absent actor off the body", async () => {
    const posted: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      posted.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      const path = String(_url);
      const ack = path.includes("/v1/events")
        ? { accepted: true, stream_seq: 1, ingest_id: "ing-1" }
        : { trace_id: "tr", decision: "allow", score: 1 };
      return new Response(JSON.stringify(ack), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const decisions = new DecisionClient({
      baseUrl: "http://api:8000",
      autoCollectSignals: false,
    });
    await decisions.evaluate({
      tenant_id: "t",
      event_type: "login",
      entity_id: "u",
      payload: { a: 1 },
    });
    await decisions.evaluate({
      tenant_id: "t",
      event_type: "login",
      entity_id: "u",
      actor_kind: "agent",
      mandate_caps: {},
      mandate_expires_at: "2020-01-01T00:00:00Z",
    });

    const ingest = new EventIngestClient({ baseUrl: "http://ingest:8001" });
    await ingest.sendEvent({
      tenant_id: "t",
      event_type: "login",
      entity_id: "u",
      actor_kind: "agent",
      mandate_caps: { spend_limit: 5 },
      mandate_expires_at: "2099-01-01T00:00:00Z",
    });

    expect(posted[0].actor_kind).toBeUndefined();
    expect(posted[0].score).toBeUndefined();
    expect(posted[0].decision).toBeUndefined();
    expect(posted[1].actor_kind).toBe("agent");
    expect(posted[1].mandate_caps).toBeUndefined();
    expect(posted[1].mandate_expired).toBe(true);
    expect(posted[1].score).toBeUndefined();
    expect(posted[2].actor_kind).toBe("agent");
    expect(posted[2].mandate_caps).toEqual({ spend_limit: 5 });
    expect(posted[2].mandate_expired).toBeUndefined();
    expect(posted[2].score).toBeUndefined();
    vi.unstubAllGlobals();
  });
});
