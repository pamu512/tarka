import { jsPDF } from "jspdf";
import type { Case, EntityRiskResult } from "../api/client";
import type { InferenceContext } from "../api/inferenceContext";

/** Plain snapshot for PDF — no React nodes, no raw JSON envelopes. */
export type CaseWorkspaceEvidenceSnapshot = {
  generatedAtIso: string;
  productName: string;
  caseTitle: string;
  workspaceTab: "timeline" | "audit" | "graph";
  caseStatus: string;
  casePriority: string;
  slaOnTrack: boolean;
  /** Abbreviated opaque identifiers for counsel-safe reference */
  caseRef: string;
  entityRef: string;
  traceRef: string | null;
  orgEnvironmentLabel: string;
  assignedTeam: string | null;
  labels: string[];
  triage: {
    verdict: string;
    score: number;
    sightLine: string | null;
    flashCards: Array<{ title: string; value: string }>;
    financialLine: string | null;
    velocity24h: string | null;
    queueScore: string | null;
    graphRiskDisplay: string | null;
  };
  decision: {
    ruleHits: string[];
    tags: string[];
    recommendedAction: string | null;
    mlSummaryExcerpt: string | null;
    topSignals: string[];
    driverReasons: string[];
  } | null;
  graphRiskPanel: {
    riskScore: number;
    communitySize: number | null;
    riskFactors: string[];
  } | null;
  graphLockerSummary: string | null;
  comments: Array<{ author: string; text: string; timestamp: string }>;
};

const PAGE_MARGIN_PT = 48;
const LINE_PT = 12;
const TITLE_PT = 16;
const SUBTITLE_PT = 11;

/** Shorten UUID-like / long opaque strings for external PDFs. */
export function abbreviateOpaqueId(id: string): string {
  const t = id.trim();
  if (!t) return "—";
  if (t.length <= 14) return t;
  if (/^[0-9a-f-]{36}$/i.test(t)) {
    return `${t.slice(0, 8)}…${t.slice(-4)}`;
  }
  return `${t.slice(0, 6)}…${t.slice(-4)}`;
}

/** Remove emails, URLs, and trim length for legal-team PDF body text. */
export function sanitizeEvidenceText(input: string, maxLen = 8000): string {
  let s = input.replace(/\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b/gi, "[email redacted]");
  s = s.replace(/\bhttps?:\/\/[^\s<>"')]+/gi, "[URL removed]");
  s = s.replace(/\s+/g, " ").trim();
  if (s.length > maxLen) {
    s = `${s.slice(0, maxLen - 1)}…`;
  }
  return s;
}

function tabLabel(tab: CaseWorkspaceEvidenceSnapshot["workspaceTab"]): string {
  switch (tab) {
    case "timeline":
      return "Timeline (comments)";
    case "audit":
      return "Audit";
    case "graph":
      return "Entity graph";
    default:
      return tab;
  }
}

function startPdf(): { doc: jsPDF; y: number; pageInnerWidth: number; pageHeight: number } {
  const doc = new jsPDF({ unit: "pt", format: "letter" });
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const pageInnerWidth = pageWidth - PAGE_MARGIN_PT * 2;
  return { doc, y: PAGE_MARGIN_PT, pageInnerWidth, pageHeight };
}

function ensureSpace(
  doc: jsPDF,
  y: number,
  needed: number,
  pageHeight: number,
): { doc: jsPDF; y: number } {
  if (y + needed <= pageHeight - PAGE_MARGIN_PT) return { doc, y };
  doc.addPage();
  return { doc, y: PAGE_MARGIN_PT };
}

function addLines(
  doc: jsPDF,
  y: number,
  lines: string[],
  pageInnerWidth: number,
  pageHeight: number,
  fontSize = SUBTITLE_PT,
): number {
  doc.setFontSize(fontSize);
  doc.setFont("helvetica", "normal");
  let cy = y;
  for (const raw of lines) {
    const wrapped = doc.splitTextToSize(raw, pageInnerWidth);
    const blockH = wrapped.length * LINE_PT + 4;
    const space = ensureSpace(doc, cy, blockH, pageHeight);
    cy = space.y;
    doc.text(wrapped, PAGE_MARGIN_PT, cy + LINE_PT - 2);
    cy += wrapped.length * LINE_PT;
  }
  return cy + 6;
}

function addHeading(doc: jsPDF, y: number, text: string, pageHeight: number): number {
  const space = ensureSpace(doc, y, LINE_PT + 8, pageHeight);
  doc.setFontSize(12);
  doc.setFont("helvetica", "bold");
  doc.text(text, PAGE_MARGIN_PT, space.y + LINE_PT);
  return space.y + LINE_PT + 10;
}

export function buildCaseWorkspaceEvidencePdfBlob(snapshot: CaseWorkspaceEvidenceSnapshot): Blob {
  const { doc, y: y0, pageInnerWidth, pageHeight } = startPdf();
  let y = y0;

  doc.setFontSize(TITLE_PT);
  doc.setFont("helvetica", "bold");
  doc.text("Evidence export (sanitized)", PAGE_MARGIN_PT, y + LINE_PT);
  y += LINE_PT + 8;

  doc.setFontSize(SUBTITLE_PT);
  doc.setFont("helvetica", "normal");
  y = addLines(
    doc,
    y,
    [
      `${snapshot.productName} — case workspace snapshot for legal / compliance review.`,
      `Generated (UTC): ${snapshot.generatedAtIso}`,
      "Internal URLs, raw JSON envelopes, and full opaque identifiers are omitted or abbreviated.",
    ],
    pageInnerWidth,
    pageHeight,
    10,
  );

  y = addHeading(doc, y, "Case overview", pageHeight);
  y = addLines(
    doc,
    y,
    [
      `Title: ${sanitizeEvidenceText(snapshot.caseTitle, 500)}`,
      `Status: ${snapshot.caseStatus} · Priority: ${snapshot.casePriority}`,
      `SLA: ${snapshot.slaOnTrack ? "On track" : "Breached or past deadline"}`,
      `Active workspace tab: ${tabLabel(snapshot.workspaceTab)}`,
      `Case ref: ${snapshot.caseRef}`,
      `Subject entity ref: ${snapshot.entityRef}`,
      snapshot.traceRef ? `Decision trace ref: ${snapshot.traceRef}` : "Decision trace ref: not linked",
      `Environment: ${sanitizeEvidenceText(snapshot.orgEnvironmentLabel, 120)}`,
      snapshot.assignedTeam
        ? `Assigned team: ${sanitizeEvidenceText(snapshot.assignedTeam, 200)}`
        : "Assigned team: —",
      snapshot.labels.length ? `Labels: ${snapshot.labels.map((l) => sanitizeEvidenceText(l, 80)).join(", ")}` : "Labels: —",
    ],
    pageInnerWidth,
    pageHeight,
  );

  y = addHeading(doc, y, "Triage summary", pageHeight);
  const tri = snapshot.triage;
  const triLines = [
    `Verdict: ${tri.verdict} · Risk score: ${Number.isFinite(tri.score) ? tri.score.toFixed(1) : "—"} / 100`,
    tri.sightLine ? `Summary line: ${sanitizeEvidenceText(tri.sightLine, 600)}` : null,
    ...tri.flashCards.map((c) => `${c.title}: ${sanitizeEvidenceText(c.value, 200)}`),
    tri.financialLine,
    tri.velocity24h != null ? `Velocity (24h events): ${tri.velocity24h}` : null,
    tri.queueScore != null ? `Queue score: ${tri.queueScore}` : null,
    tri.graphRiskDisplay != null ? `Graph risk (display): ${tri.graphRiskDisplay}` : null,
  ].filter((x): x is string => Boolean(x));
  y = addLines(doc, y, triLines, pageInnerWidth, pageHeight);

  if (snapshot.decision) {
    y = addHeading(doc, y, "Decision audit (high level)", pageHeight);
    const d = snapshot.decision;
    const decLines = [
      d.recommendedAction ? `Recommended action: ${sanitizeEvidenceText(d.recommendedAction, 300)}` : null,
      d.ruleHits.length ? `Rule hits: ${d.ruleHits.map((x) => sanitizeEvidenceText(x, 120)).join("; ")}` : "Rule hits: —",
      d.tags.length ? `Tags: ${d.tags.map((x) => sanitizeEvidenceText(x, 120)).join("; ")}` : null,
      d.topSignals.length ? `Top signals: ${d.topSignals.map((x) => sanitizeEvidenceText(x, 120)).join("; ")}` : null,
      d.driverReasons.length
        ? `Driver reasons:\n${d.driverReasons.map((x) => `  - ${sanitizeEvidenceText(x, 400)}`).join("\n")}`
        : null,
      d.mlSummaryExcerpt ? `ML narrative (excerpt):\n${sanitizeEvidenceText(d.mlSummaryExcerpt, 3500)}` : null,
    ].filter((x): x is string => Boolean(x));
    y = addLines(doc, y, decLines.length ? decLines : ["No linked decision audit fields."], pageInnerWidth, pageHeight);
  }

  if (snapshot.graphRiskPanel) {
    y = addHeading(doc, y, "Graph risk context", pageHeight);
    const g = snapshot.graphRiskPanel;
    y = addLines(
      doc,
      y,
      [
        `Graph risk score (0–1): ${g.riskScore.toFixed(3)}`,
        g.communitySize != null ? `Community size: ${g.communitySize}` : null,
        g.riskFactors.length
          ? `Risk factors: ${g.riskFactors.map((x) => sanitizeEvidenceText(x, 200)).join("; ")}`
          : null,
      ].filter((x): x is string => Boolean(x)),
      pageInnerWidth,
      pageHeight,
    );
  }

  if (snapshot.graphLockerSummary) {
    y = addHeading(doc, y, "Evidence locker snapshot", pageHeight);
    y = addLines(doc, y, [sanitizeEvidenceText(snapshot.graphLockerSummary, 500)], pageInnerWidth, pageHeight);
  }

  y = addHeading(doc, y, "Case comments (timeline)", pageHeight);
  if (snapshot.comments.length === 0) {
    y = addLines(doc, y, ["No comments recorded on this case."], pageInnerWidth, pageHeight);
  } else {
    for (const c of snapshot.comments) {
      const block = `${c.timestamp} — ${sanitizeEvidenceText(c.author, 120)}:\n${sanitizeEvidenceText(c.text, 2000)}`;
      y = addLines(doc, y, [block], pageInnerWidth, pageHeight);
      y += 4;
    }
  }

  y = ensureSpace(doc, y, LINE_PT * 4, pageHeight).y;
  doc.setFontSize(9);
  doc.setFont("helvetica", "italic");
  doc.setTextColor(100, 100, 100);
  const disc = doc.splitTextToSize(
    "This PDF is a sanitized derivative for disclosure workflows. It is not a substitute for full system records.",
    pageInnerWidth,
  );
  doc.text(disc, PAGE_MARGIN_PT, y + LINE_PT);
  doc.setTextColor(0, 0, 0);

  return doc.output("blob");
}

export function caseEvidenceExportPdfFilename(caseId: string): string {
  const ymd = new Date().toISOString().slice(0, 10);
  const short = caseId.replace(/[^a-zA-Z0-9]/g, "").slice(0, 12) || "case";
  return `tarka-evidence-${short}-${ymd}.pdf`;
}

/** Build snapshot from loaded CaseDetail state (caller supplies tab + derived fields). */
export function buildCaseWorkspaceEvidenceSnapshot(args: {
  caseData: Case;
  activeTab: CaseWorkspaceEvidenceSnapshot["workspaceTab"];
  slaOnTrack: boolean;
  sightLine: string | null;
  flashCardsPlain: Array<{ title: string; value: string }>;
  financialLine: string | null;
  velocity24h: number | null;
  queueScore: number | null;
  graphRiskDisplay: string | null;
  decisionExplain: {
    score: number;
    decision: string;
    tags: string[];
    rule_hits: string[];
    recommended_action?: string | null;
    inference_context: InferenceContext | null;
  } | null;
  graphRisk: EntityRiskResult | null;
}): CaseWorkspaceEvidenceSnapshot {
  const {
    caseData,
    activeTab,
    slaOnTrack,
    sightLine,
    flashCardsPlain,
    financialLine,
    velocity24h,
    queueScore,
    graphRiskDisplay,
    decisionExplain,
    graphRisk,
  } = args;

  const ic = decisionExplain?.inference_context ?? null;
  const ml = ic?.ml_summary?.trim() ?? "";

  let graphLockerSummary: string | null = null;
  const snap = caseData.graph_snapshot;
  if (snap && typeof snap === "object") {
    const nodes = Array.isArray((snap as { nodes?: unknown }).nodes)
      ? (snap as { nodes: unknown[] }).nodes.length
      : null;
    const edges = Array.isArray((snap as { edges?: unknown }).edges)
      ? (snap as { edges: unknown[] }).edges.length
      : null;
    if (nodes != null || edges != null) {
      graphLockerSummary = `Locker graph: ${nodes ?? "?"} nodes, ${edges ?? "?"} edges (structure only; interactive graph not reproduced here).`;
    }
  }

  return {
    generatedAtIso: new Date().toISOString(),
    productName: "Tarka",
    caseTitle: caseData.title,
    workspaceTab: activeTab,
    caseStatus: caseData.status,
    casePriority: caseData.priority,
    slaOnTrack,
    caseRef: abbreviateOpaqueId(caseData.id),
    entityRef: abbreviateOpaqueId(caseData.entity_id),
    traceRef: caseData.trace_id ? abbreviateOpaqueId(caseData.trace_id) : null,
    orgEnvironmentLabel: caseData.tenant_id,
    assignedTeam: caseData.assigned_team ?? null,
    labels: caseData.labels ?? [],
    triage: {
      verdict: decisionExplain?.decision ?? "review",
      score: decisionExplain?.score ?? 0,
      sightLine,
      flashCards: flashCardsPlain,
      financialLine,
      velocity24h: velocity24h != null && Number.isFinite(velocity24h) ? String(velocity24h) : null,
      queueScore:
        queueScore != null && Number.isFinite(queueScore) ? queueScore.toFixed(1) : null,
      graphRiskDisplay,
    },
    decision: decisionExplain
      ? {
          ruleHits: decisionExplain.rule_hits ?? [],
          tags: decisionExplain.tags ?? [],
          recommendedAction: decisionExplain.recommended_action ?? null,
          mlSummaryExcerpt: ml ? ml : null,
          topSignals: ic?.top_signals ?? [],
          driverReasons: ic?.driver_reasons ?? [],
        }
      : null,
    graphRiskPanel: graphRisk
      ? {
          riskScore: graphRisk.risk_score,
          communitySize: graphRisk.community_size ?? null,
          riskFactors: graphRisk.risk_factors ?? [],
        }
      : null,
    graphLockerSummary,
    comments: caseData.comments ?? [],
  };
}
