import { describe, expect, it } from "vitest";
import {
  attachInTransitIntegrityFields,
  canonicalUnifiedSignalJsonExcludingNonce,
  computeInTransitIntegrityHash,
} from "../src/integrity.js";

describe("integrity", () => {
  it("canonical excludes n and ih and sorts keys", () => {
    const c = canonicalUnifiedSignalJsonExcludingNonce({
      z: 1,
      a: 2,
      n: "nonce",
      ih: "deadbeef",
    });
    expect(c).toBe('{"a":2,"z":1}');
  });

  it("canonical excludes gc and gct (server-side geo)", () => {
    const c = canonicalUnifiedSignalJsonExcludingNonce({
      z: 1,
      gc: "US",
      gct: "NYC",
      n: "n",
      ih: "h",
    });
    expect(c).toBe('{"z":1}');
  });

  it("computeInTransitIntegrityHash returns 64 hex chars", async () => {
    const h = await computeInTransitIntegrityHash({ a: 1 }, "nonce-x");
    expect(h).toMatch(/^[0-9a-f]{64}$/);
  });

  it("attachInTransitIntegrityFields adds n and ih", async () => {
    const out = await attachInTransitIntegrityFields({ ch: "c".repeat(64), sid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" }, "srv-nonce-1");
    expect(out.n).toBe("srv-nonce-1");
    expect(out.ih).toMatch(/^[0-9a-f]{64}$/);
  });
});
