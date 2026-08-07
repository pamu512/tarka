import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import DisputeReviewByIdPage from "@/pages/disputes/[id]";

/** Must match ``mockDisputes[0].shadow_evidence_report_markdown`` digest line (Prompt 127 gate). */
const EXPECTED_CRYPTO_EVENT_HASH =
  "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbcccccccccccccccccccccccccccccccc";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    disputes: {
      ...actual.disputes,
      get: vi.fn(),
      reprocessExternal: vi.fn(),
    },
  };
});

describe("Dispute review UI (Prompt 127)", () => {
  beforeEach(() => {
    vi.mocked(client.disputes.get).mockResolvedValue({
      id: "d1",
      case_id: "c1",
      tenant_id: "demo",
      entity_id: "fraud_frank",
      trace_id: "trace-d1",
      dispute_type: "chargeback",
      status: "open",
      reason_code: "4853",
      amount: 100,
      currency: "USD",
      merchant_id: null,
      card_network: null,
      original_decision: null,
      original_score: null,
      original_rule_hits: [],
      original_ml_score: null,
      outcome: null,
      resolution_notes: null,
      filed_at: null,
      resolved_at: null,
      created_at: null,
      updated_at: null,
      evidence_pdf_url:
        "https://www.w3.org/WAI/WCAG21/working-examples/pdf-note/note.pdf",
      shadow_evidence_report_markdown:
        "## Shadow AI evidence report (sample)\n\n" +
        "SHA-256 event digest (hex): `" +
        EXPECTED_CRYPTO_EVENT_HASH +
        "`\n",
      is_friendly_fraud_risk: true,
      latest_decision_reprocess: {
        ok: true,
        decision: "review",
        score: 77,
        tags: ["risk:refund_burst"],
        degraded: false,
      },
    } as client.DisputeEntry);
    vi.mocked(client.disputes.reprocessExternal).mockResolvedValue({
      ok: true,
      dispute_id: "d1",
      tenant_id: "demo",
      reprocessed_at: new Date().toISOString(),
      external_reprocess_count: 1,
      reason: "test",
      idempotent_replay: false,
    });
  });

  it("loads PDF panel and Shadow evidence panel for sample dispute d1", async () => {
    render(
      <MemoryRouter initialEntries={["/disputes/d1"]}>
        <Routes>
          <Route path="/disputes/:id" element={<DisputeReviewByIdPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("dispute-review-split")).toBeInTheDocument();
    });

    expect(screen.getByTestId("dispute-review-id")).toHaveTextContent("d1");

    const iframe = screen.getByTestId("dispute-review-pdf-iframe") as HTMLIFrameElement;
    expect(iframe.src).toContain("note.pdf");

    const report = screen.getByTestId("dispute-review-shadow-report");
    expect(report.textContent).toContain("Shadow AI evidence report");
    expect(report.textContent).toContain(EXPECTED_CRYPTO_EVENT_HASH);

    expect(screen.getByTestId("dispute-review-pdf-panel")).toBeInTheDocument();
    expect(screen.getByTestId("dispute-review-shadow-panel")).toBeInTheDocument();
  });

  it("shows reprocess panel with friendly fraud badge and reprocess action", async () => {
    render(
      <MemoryRouter initialEntries={["/disputes/d1"]}>
        <Routes>
          <Route path="/disputes/:id" element={<DisputeReviewByIdPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("dispute-reprocess-panel")).toBeInTheDocument();
    });

    expect(screen.getByTestId("dispute-friendly-fraud-badge")).toHaveTextContent("Yes");
    expect(screen.getByTestId("dispute-reprocess-details")).toHaveTextContent("review");
    expect(screen.getByTestId("dispute-reprocess-details")).toHaveTextContent("77.0");
    expect(screen.getByTestId("dispute-reprocess-details")).toHaveTextContent("risk:refund_burst");

    fireEvent.click(screen.getByTestId("dispute-reprocess-button"));
    await waitFor(() => {
      expect(client.disputes.reprocessExternal).toHaveBeenCalled();
    });
  });
});
