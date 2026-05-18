import { describe, expect, it } from "vitest";
import {
  abbreviateOpaqueId,
  buildCaseWorkspaceEvidencePdfBlob,
  buildCaseWorkspaceEvidenceSnapshot,
  sanitizeEvidenceText,
} from "./evidenceExportPdf";

describe("abbreviateOpaqueId", () => {
  it("passes through short ids", () => {
    expect(abbreviateOpaqueId("demo")).toBe("demo");
  });

  it("abbreviates UUID-shaped strings", () => {
    expect(abbreviateOpaqueId("550e8400-e29b-41d4-a716-446655440000")).toMatch(/^550e8400…0000$/);
  });
});

describe("sanitizeEvidenceText", () => {
  it("redacts emails and URLs", () => {
    expect(sanitizeEvidenceText("Contact fraud@bank.com see https://internal.example/x")).toBe(
      "Contact [email redacted] see [URL removed]",
    );
  });
});

describe("buildCaseWorkspaceEvidencePdfBlob", () => {
  it("produces a non-empty PDF blob", () => {
    const snapshot = buildCaseWorkspaceEvidenceSnapshot({
      caseData: {
        id: "case-full-uuid-000000000000",
        title: "Wire review",
        status: "investigating",
        priority: "high",
        entity_id: "ent-550e8400-e29b-41d4-a716-446655440000",
        tenant_id: "demo",
        trace_id: "trace-550e8400-e29b-41d4-a716-446655440000",
        assigned_team: "Team A",
        labels: ["sar"],
        comments: [{ author: "analyst", text: "Escalated.", timestamp: "2026-01-01T00:00:00Z" }],
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        graph_snapshot: { nodes: [{}], edges: [] },
      },
      activeTab: "timeline",
      slaOnTrack: true,
      sightLine: "Manual review recommended.",
      flashCardsPlain: [
        { title: "Velocity", value: "Normal" },
        { title: "Graph", value: "Elevated" },
        { title: "Geo", value: "Consistent" },
      ],
      financialLine: null,
      velocity24h: 3,
      queueScore: 42,
      graphRiskDisplay: "0.120",
      decisionExplain: null,
      graphRisk: null,
    });
    const blob = buildCaseWorkspaceEvidencePdfBlob(snapshot);
    expect(blob.size).toBeGreaterThan(500);
    expect(blob.type).toBe("application/pdf");
  });
});
