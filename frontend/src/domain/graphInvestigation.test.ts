import { describe, expect, it } from "vitest";

import {
  entityExportPath,
  parseAsOfParam,
  parseGraphWorkspaceParams,
  summarizeEntityExport,
  validateAsOfInput,
} from "./graphInvestigation";

describe("as-of workspace params (bitemporal reads)", () => {
  it("parses a valid as_of timestamp from the URL", () => {
    const sp = new URLSearchParams({ entity_id: "u1", as_of: "2026-09-01T00:00:00Z" });
    const parsed = parseGraphWorkspaceParams(sp, "demo");
    expect(parsed.asOf).toBe("2026-09-01T00:00:00Z");
  });

  it("treats a garbage as_of as absent rather than sending it upstream", () => {
    const sp = new URLSearchParams({ entity_id: "u1", as_of: "evaluate" });
    const parsed = parseGraphWorkspaceParams(sp, "demo");
    expect(parsed.asOf).toBeNull();
  });

  it("absent as_of is null (live graph)", () => {
    const parsed = parseGraphWorkspaceParams(new URLSearchParams({ entity_id: "u1" }), "demo");
    expect(parsed.asOf).toBeNull();
  });

  it("validateAsOfInput accepts ISO timestamps and rejects placeholders", () => {
    expect(validateAsOfInput("2026-09-01T12:00:00Z")).toBeNull();
    expect(validateAsOfInput("evaluate")).toMatch(/timestamp/i);
    expect(validateAsOfInput("")).toBeNull();
  });

  it("parseAsOfParam normalizes Z suffix", () => {
    expect(parseAsOfParam("2026-09-01T00:00:00+00:00")).toBe("2026-09-01T00:00:00Z");
    expect(parseAsOfParam("not-a-time")).toBeNull();
  });
});

describe("entity export (DSAR surface)", () => {
  it("entityExportPath builds the graph-plane export URL with tenant scope", () => {
    expect(entityExportPath("vol-user-1", "t1")).toBe(
      "/api/graph/v1/entities/vol-user-1/export?tenant_id=t1",
    );
    expect(entityExportPath("id with space", "t1")).toContain(encodeURIComponent("id with space"));
  });

  it("summarizeEntityExport counts nodes/edges and flags context", () => {
    expect(
      summarizeEntityExport({ nodes: [{}, {}, {}], edges: [{}], deep_context: { a: 1 } }),
    ).toBe("3 node(s), 1 edge(s) — context included");
    expect(summarizeEntityExport({})).toBe("0 node(s), 0 edge(s) — no context");
  });
});
