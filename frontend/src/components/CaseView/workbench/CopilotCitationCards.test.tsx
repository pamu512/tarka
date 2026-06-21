import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CopilotCitationCards } from "./CopilotCitationCards";

describe("CopilotCitationCards", () => {
  it("renders citation anchors", () => {
    render(
      <CopilotCitationCards
        citations={[
          {
            claim_index: 1,
            text: "Velocity spike on device cluster",
            source: "audit",
            supported: true,
            confidence_label: "high",
            resolves_to: [{ artifact: "decision_trace", id: "trace-1" }],
          },
        ]}
      />,
    );
    expect(screen.getByText(/Velocity spike/)).toBeInTheDocument();
    expect(screen.getByText(/decision_trace:trace-1/)).toBeInTheDocument();
  });

  it("shows empty helper copy", () => {
    render(<CopilotCitationCards citations={[]} />);
    expect(screen.getByText(/Ask the copilot/)).toBeInTheDocument();
  });
});
