import { describe, expect, it } from "vitest";

import { sanitizeErrorPayloadForDisplay } from "./sanitizeErrorPayload";

describe("sanitizeErrorPayloadForDisplay", () => {
  it("redacts known token fields and nested secrets", () => {
    const raw = {
      detail: "Validation failed",
      support_id: "abc-123",
      error: { code: "bad_request", message: "oops" },
      access_token: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
      nested: { refresh_token: "keep-secret", ok: true },
    };
    const out = sanitizeErrorPayloadForDisplay(raw) as Record<string, unknown>;
    expect(out.access_token).toBe("[REDACTED]");
    expect((out.nested as Record<string, unknown>).refresh_token).toBe("[REDACTED]");
    expect((out.nested as Record<string, unknown>).ok).toBe(true);
    expect(out.detail).toBe("Validation failed");
  });

  it("redacts Bearer headers and bare JWT-looking strings", () => {
    const out = sanitizeErrorPayloadForDisplay({
      authorization: "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
      note: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
    }) as Record<string, unknown>;
    expect(out.authorization).toBe("[REDACTED]");
    expect(out.note).toBe("[REDACTED JWT]");
  });
});
