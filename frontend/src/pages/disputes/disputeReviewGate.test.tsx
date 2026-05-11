import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import DisputeReviewByIdPage from "@/pages/disputes/[id]";

/** Must match ``mockDisputes[0].shadow_evidence_report_markdown`` digest line (Prompt 127 gate). */
const EXPECTED_CRYPTO_EVENT_HASH =
  "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbcccccccccccccccccccccccccccccccc";

describe("Dispute review UI (Prompt 127)", () => {
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
