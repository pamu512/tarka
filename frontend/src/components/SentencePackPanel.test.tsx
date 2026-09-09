import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SentencePackPanel } from "./SentencePackPanel";

describe("SentencePackPanel", () => {
  it("keeps the live JSON preview mounted and updates it when the sentence changes", () => {
    render(<SentencePackPanel onJson={() => undefined} />);
    const preview = screen.getByTestId("sentence-pack-json-preview") as HTMLTextAreaElement;
    expect(preview).toBeInTheDocument();
    expect(preview.value).toContain("event_count_1h");
    expect(preview.value).toContain('"mode": "shadow"');
    fireEvent.change(screen.getByDisplayValue("20"), { target: { value: "40" } });
    expect((screen.getByTestId("sentence-pack-json-preview") as HTMLTextAreaElement).value).toContain("40");
  });
});
