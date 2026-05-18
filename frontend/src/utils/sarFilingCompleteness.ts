import type { SarFilingIntentDetail, SarFilingIntentStatus, SarIntentDetailResponse } from "../api/client";

/** Minimum plain-text length after stripping HTML for a substantive SAR narrative. */
export const SAR_MIN_NARRATIVE_CHARS = 40;

const POST_FILE_STATUSES = new Set<SarFilingIntentStatus>([
  "FILED",
  "SFTP_QUEUED",
  "TRANSMITTED",
  "ACKNOWLEDGED",
  "FAILED",
]);

export type SarCheckState = "satisfied" | "missing" | "pending" | "unknown";

export interface SarFilingCheckRow {
  id: "narrative" | "approval" | "artifact" | "digest";
  label: string;
  regulatoryHint: string;
  state: SarCheckState;
  remediation: string | null;
}

export interface SarFilingReadiness {
  percentComplete: number;
  rows: SarFilingCheckRow[];
  missingLabels: string[];
}

export function stripHtmlToPlainText(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function narrativeSatisfied(html: string): boolean {
  return stripHtmlToPlainText(html).length >= SAR_MIN_NARRATIVE_CHARS;
}

function rowsToPercent(rows: SarFilingCheckRow[]): number {
  const scored = rows.filter((r) => r.state === "satisfied" || r.state === "missing");
  if (scored.length === 0) return 100;
  const ok = scored.filter((r) => r.state === "satisfied").length;
  return Math.round((100 * ok) / scored.length);
}

/** Full checklist from SAR workspace detail (optionally uses unsaved draft HTML for narrative). */
export function evaluateSarFilingReadinessFromDetail(
  detail: SarIntentDetailResponse,
  draftNotesHtml?: string,
): SarFilingReadiness {
  const notesSource =
    detail.notes_editor_locked ? detail.investigative_notes_html : (draftNotesHtml ?? detail.investigative_notes_html);

  const narrativeOk = narrativeSatisfied(notesSource ?? "");

  const approvalMissing = detail.status === "PENDING_REVIEW";

  const artifactApplicable = POST_FILE_STATUSES.has(detail.status);
  const artifactMissing = artifactApplicable && !detail.sar_artifact_id;

  const digestApplicable = detail.notes_editor_locked === true;
  const digestMissing = digestApplicable && !detail.fincen_submission_sha256_hex;

  const rows: SarFilingCheckRow[] = [
    {
      id: "narrative",
      label: "Investigative narrative",
      regulatoryHint: "SAR supporting narrative (plain-language description of activity).",
      state: narrativeOk ? "satisfied" : "missing",
      remediation: narrativeOk
        ? null
        : `Add at least ${SAR_MIN_NARRATIVE_CHARS} characters of substantive narrative in Investigative notes (save when ready).`,
    },
    {
      id: "approval",
      label: "Compliance approval for filing",
      regulatoryHint: "Human analyst attestation before the SAR package is filed.",
      state: approvalMissing ? "missing" : "satisfied",
      remediation: approvalMissing
        ? "Enter your analyst user ID and choose Approve for filing (or wait for compliance review)."
        : null,
    },
    {
      id: "artifact",
      label: "SAR batch artifact (package)",
      regulatoryHint: "FinCEN-bound SAR XML / batch produced for this intent.",
      state: !artifactApplicable ? "pending" : artifactMissing ? "missing" : "satisfied",
      remediation: !artifactApplicable
        ? null
        : artifactMissing
          ? "Expected after filing completes; if stuck, check audit trail and case-api logs."
          : null,
    },
    {
      id: "digest",
      label: "FinCEN wire payload digest (SHA-256)",
      regulatoryHint: "Immutable checksum of on-the-wire bytes after upload (Uploaded lock).",
      state: !digestApplicable ? "pending" : digestMissing ? "missing" : "satisfied",
      remediation: !digestApplicable
        ? null
        : digestMissing
          ? "Uploaded lock is on but no SHA-256 digest is present—verify batch build and FinCEN packaging."
          : null,
    },
  ];

  const missingLabels = rows.filter((r) => r.state === "missing").map((r) => r.label);

  return {
    percentComplete: rowsToPercent(rows),
    rows,
    missingLabels,
  };
}

/** Partial checklist from case SAR panel list row (no narrative or digest). */
export function evaluateSarFilingReadinessFromIntentSummary(intent: SarFilingIntentDetail): SarFilingReadiness {
  const approvalMissing = intent.status === "PENDING_REVIEW";

  const artifactApplicable = POST_FILE_STATUSES.has(intent.status);
  const artifactMissing = artifactApplicable && !intent.sar_artifact_id;

  const rows: SarFilingCheckRow[] = [
    {
      id: "narrative",
      label: "Investigative narrative",
      regulatoryHint: "SAR supporting narrative (plain-language description of activity).",
      state: "unknown",
      remediation: "Open the SAR intent workspace to enter narrative and see full filing readiness.",
    },
    {
      id: "approval",
      label: "Compliance approval for filing",
      regulatoryHint: "Human analyst attestation before the SAR package is filed.",
      state: approvalMissing ? "missing" : "satisfied",
      remediation: approvalMissing
        ? "Enter your analyst user ID and choose Approve for filing (or wait for compliance review)."
        : null,
    },
    {
      id: "artifact",
      label: "SAR batch artifact (package)",
      regulatoryHint: "FinCEN-bound SAR XML / batch produced for this intent.",
      state: !artifactApplicable ? "pending" : artifactMissing ? "missing" : "satisfied",
      remediation: !artifactApplicable
        ? null
        : artifactMissing
          ? "Expected after filing completes; if stuck, check audit trail and case-api logs."
          : null,
    },
    {
      id: "digest",
      label: "FinCEN wire payload digest (SHA-256)",
      regulatoryHint: "Immutable checksum of on-the-wire bytes after upload (Uploaded lock).",
      state: "unknown",
      remediation: "After transmit, open the SAR intent workspace to confirm digest when notes are locked.",
    },
  ];

  const missingLabels = rows.filter((r) => r.state === "missing").map((r) => r.label);

  return {
    percentComplete: rowsToPercent(rows),
    rows,
    missingLabels,
  };
}
