import { describe, expect, it } from "vitest";
import type { SarIntentDetailResponse } from "../api/client";
import {
  evaluateSarFilingReadinessFromDetail,
  evaluateSarFilingReadinessFromIntentSummary,
  SAR_MIN_NARRATIVE_CHARS,
  stripHtmlToPlainText,
} from "./sarFilingCompleteness";

const emptyDetail = (): SarIntentDetailResponse => ({
  case_id: "case-1",
  intent_id: "intent-1",
  status: "PENDING_REVIEW",
  sar_artifact_id: null,
  created_at: null,
  updated_at: null,
  investigative_notes_html: "",
  notes_editor_locked: false,
  fincen_submission_sha256_hex: null,
  audit_log: [],
});

describe("stripHtmlToPlainText", () => {
  it("strips tags and normalizes whitespace", () => {
    expect(stripHtmlToPlainText("<p>Hello &nbsp; <b>world</b></p>")).toBe("Hello world");
  });
});

describe("evaluateSarFilingReadinessFromDetail", () => {
  it("marks narrative missing when below minimum length", () => {
    const r = evaluateSarFilingReadinessFromDetail({
      ...emptyDetail(),
      investigative_notes_html: "<p>too short</p>",
    });
    expect(r.rows.find((x) => x.id === "narrative")?.state).toBe("missing");
    expect(r.missingLabels.some((l) => l.includes("narrative") || l === "Investigative narrative")).toBe(true);
  });

  it("accepts substantive plain text after strip", () => {
    const html = `<p>${"word ".repeat(20).trim()}</p>`;
    expect(stripHtmlToPlainText(html).length).toBeGreaterThanOrEqual(SAR_MIN_NARRATIVE_CHARS);
    const r = evaluateSarFilingReadinessFromDetail({
      ...emptyDetail(),
      investigative_notes_html: html,
    });
    expect(r.rows.find((x) => x.id === "narrative")?.state).toBe("satisfied");
  });

  it("uses draft HTML when provided and notes are not locked", () => {
    const r = evaluateSarFilingReadinessFromDetail(
      {
        ...emptyDetail(),
        investigative_notes_html: "<p>short</p>",
      },
      `<p>${"word ".repeat(20).trim()}</p>`,
    );
    expect(r.rows.find((x) => x.id === "narrative")?.state).toBe("satisfied");
  });

  it("flags approval when still pending review", () => {
    const r = evaluateSarFilingReadinessFromDetail({
      ...emptyDetail(),
      status: "PENDING_REVIEW",
      investigative_notes_html: `<p>${"x".repeat(SAR_MIN_NARRATIVE_CHARS)}</p>`,
    });
    expect(r.rows.find((x) => x.id === "approval")?.state).toBe("missing");
  });

  it("marks artifact missing post-file when id absent", () => {
    const r = evaluateSarFilingReadinessFromDetail({
      ...emptyDetail(),
      status: "FILED",
      sar_artifact_id: null,
      investigative_notes_html: `<p>${"x".repeat(SAR_MIN_NARRATIVE_CHARS)}</p>`,
    });
    expect(r.rows.find((x) => x.id === "artifact")?.state).toBe("missing");
  });

  it("marks digest missing when locked without SHA", () => {
    const r = evaluateSarFilingReadinessFromDetail({
      ...emptyDetail(),
      status: "TRANSMITTED",
      investigative_notes_html: `<p>${"x".repeat(SAR_MIN_NARRATIVE_CHARS)}</p>`,
      notes_editor_locked: true,
      fincen_submission_sha256_hex: null,
      sar_artifact_id: "artifact-1",
    });
    expect(r.rows.find((x) => x.id === "digest")?.state).toBe("missing");
  });
});

describe("evaluateSarFilingReadinessFromIntentSummary", () => {
  it("leaves narrative and digest as unknown", () => {
    const r = evaluateSarFilingReadinessFromIntentSummary({
      id: "intent-1",
      status: "APPROVED",
      sar_artifact_id: null,
      created_at: null,
      updated_at: null,
      audit_log: [],
    });
    expect(r.rows.find((x) => x.id === "narrative")?.state).toBe("unknown");
    expect(r.rows.find((x) => x.id === "digest")?.state).toBe("unknown");
  });
});
