import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionTokens, setSessionTokens } from "./authSession";
import { decisions } from "./client";

describe("client.ts request() cookie session", () => {
  beforeEach(() => {
    clearSessionTokens();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearSessionTokens();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends credentials: include and does not attach Authorization from memory", async () => {
    setSessionTokens("desk-access-token", null);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ policies: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await decisions.challengePolicies();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers.authorization).toBeUndefined();
    expect(init.credentials).toBe("include");
  });

  it("still includes cookies when no in-memory token is set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ policies: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await decisions.challengePolicies();
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers.authorization).toBeUndefined();
    expect(init.credentials).toBe("include");
  });
});
