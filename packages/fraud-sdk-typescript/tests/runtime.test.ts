import { describe, expect, it, vi } from "vitest";
import {
  describeSdkCapabilities,
  resolveCollectorTimeouts,
  withTimeoutFailOpen,
} from "../src/runtime.js";

describe("runtime guards (#44)", () => {
  it("resolveCollectorTimeouts zeroes VPN when no RTCPeerConnection", () => {
    const caps = describeSdkCapabilities();
    const t = resolveCollectorTimeouts({ ...caps, has_rtc_peer_connection: false });
    expect(t.vpn).toBe(0);
  });

  it("withTimeoutFailOpen returns fallback on slow promise", async () => {
    const slow = new Promise<string>((resolve) => {
      setTimeout(() => resolve("late"), 5000);
    });
    const out = await withTimeoutFailOpen(slow, 30, "fallback", {
      collectorName: "test",
      logTimeouts: false,
    });
    expect(out).toBe("fallback");
  });

  it("withTimeoutFailOpen resolves fast promise", async () => {
    const out = await withTimeoutFailOpen(Promise.resolve("ok"), 1000, "bad");
    expect(out).toBe("ok");
  });

  it("withTimeoutFailOpen catches rejection fail-open", async () => {
    const out = await withTimeoutFailOpen(
      Promise.reject(new Error("boom")),
      100,
      "safe",
    );
    expect(out).toBe("safe");
  });

  it("logs on timeout when logTimeouts true", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    await withTimeoutFailOpen(
      new Promise(() => {}),
      20,
      0,
      { collectorName: "x", logTimeouts: true },
    );
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
