import { describe, expect, it } from "vitest";

import {
  ApiRequestError,
  isApiRequestError,
  parseHttpErrorMessage,
  toUserFacingApiError,
} from "./client";

describe("parseHttpErrorMessage", () => {
  it("includes status, detail, code, and support_id from JSON envelope", () => {
    const headers = new Headers({ "x-correlation-id": "hdr-1" });
    const text = JSON.stringify({
      error: { message: "tenant mismatch", code: "tenant_forbidden", support_id: "body-1" },
    });
    const msg = parseHttpErrorMessage(403, "Forbidden", text, headers);
    expect(msg).toMatch(/^403 tenant mismatch/);
    expect(msg).toContain("code=tenant_forbidden");
    expect(msg).toContain("support_id=body-1");
  });
});

describe("ApiRequestError + toUserFacingApiError", () => {
  const ctx = { subject: "Dashboard", action: "load dashboard metrics" };

  it("wraps HTTP failures with structured status", () => {
    const err = new ApiRequestError("404 dashboard slice missing", { status: 404 });
    expect(isApiRequestError(err)).toBe(true);
    expect(toUserFacingApiError(err, ctx)).toContain("was not found");
  });

  it("maps 401/403/404/422/5xx/network-off for core analyst workflows", () => {
    const cases = [
      ["401 Unauthorized", "do not have permission"],
      ["403 Forbidden", "do not have permission"],
      ["404 not found", "was not found"],
      ["422 invalid filter", "Some input is invalid"],
      ["500 internal error", "temporarily unavailable"],
      [new TypeError("Failed to fetch"), "unreachable from the browser"],
    ] as const;

    for (const [raw, needle] of cases) {
      expect(toUserFacingApiError(raw, ctx)).toContain(needle);
    }
  });
});
