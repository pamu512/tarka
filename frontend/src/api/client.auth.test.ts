import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionTokens, setSessionTokens } from "./authSession";
import { decisions } from "./client";

describe("client.ts request() bearer", () => {
  beforeEach(() => {
    clearSessionTokens();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearSessionTokens();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends Authorization: Bearer when a session token is stored", async () => {
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
    expect(headers.Authorization).toBe("Bearer desk-access-token");
  });

  it("omits Authorization when no session token is stored", async () => {
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
  });
});

