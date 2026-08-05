import { render, screen, waitFor } from "@testing-library/react";
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
      status: "open",
      evidence_pdf_url:
        "https://www.w3.org/WAI/WCAG21/working-examples/pdf-note/note.pdf",
      shadow_evidence_report_markdown:
        "## Shadow AI evidence report (sample)\n\n" +
        "SHA-256 event digest (hex): `" +
        EXPECTED_CRYPTO_EVENT_HASH +
        "`\n",
    } as client.DisputeEntry);
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
});
