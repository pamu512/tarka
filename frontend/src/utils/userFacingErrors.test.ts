import { describe, expect, it } from "vitest";

import { toUserFacingError } from "./userFacingErrors";

const ctx = { subject: "Case queue", action: "load cases" };

describe("toUserFacingError", () => {
  it("maps 401 to permission copy", () => {
    const msg = toUserFacingError(new Error("401 Unauthorized support_id=auth-001"), ctx);
    expect(msg).toContain("do not have permission");
    expect(msg).toContain("Support ID: auth-001");
  });

  it("maps 403 to permission copy", () => {
    const msg = toUserFacingError(new Error("403 Forbidden"), ctx);
    expect(msg).toContain("do not have permission");
  });

  it("maps 404 to not-found copy", () => {
    const msg = toUserFacingError(new Error("404 Case not found"), ctx);
    expect(msg).toContain("was not found");
  });

  it("maps 422 to validation copy", () => {
    const msg = toUserFacingError(new Error("422 validation failed"), ctx);
    expect(msg).toContain("Some input is invalid");
  });

  it("maps 5xx to temporarily unavailable copy", () => {
    const msg = toUserFacingError(new Error("503 upstream unavailable support_id=svc-9001"), ctx);
    expect(msg).toContain("temporarily unavailable");
    expect(msg).toContain("Support ID: svc-9001");
  });

  it("maps network-off / failed to fetch copy", () => {
    const msg = toUserFacingError(new TypeError("Failed to fetch"), ctx);
    expect(msg).toContain("unreachable from the browser");
  });
});
