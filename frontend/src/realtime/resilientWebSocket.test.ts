import { describe, expect, it } from "vitest";

import { nextReconnectDelayMs, WS_RECONNECT_BASE_MS, WS_RECONNECT_MAX_MS } from "./resilientWebSocket";

describe("nextReconnectDelayMs", () => {
  it("doubles exponentially from the base delay until capped", () => {
    expect(nextReconnectDelayMs(0)).toBe(WS_RECONNECT_BASE_MS);
    expect(nextReconnectDelayMs(1)).toBe(WS_RECONNECT_BASE_MS * 2);
    expect(nextReconnectDelayMs(2)).toBe(WS_RECONNECT_BASE_MS * 4);
  });

  it("never exceeds the configured ceiling", () => {
    expect(nextReconnectDelayMs(40)).toBe(WS_RECONNECT_MAX_MS);
  });
});
