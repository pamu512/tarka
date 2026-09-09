import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import VisualRuleBuilder from "@/pages/VisualRuleBuilder";

vi.mock("@/domain/authorCatalogSession", () => ({
  loadAuthorCatalog: () => Promise.resolve(null),
}));

describe("VisualRuleBuilder husk", () => {
  it("is honesty pointing at SentencePackPanel, not a product SKU", () => {
    render(
      <MemoryRouter>
        <VisualRuleBuilder />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: /legacy canvas/i })).toBeInTheDocument();
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/not a product SKU/i);
    expect(body).toMatch(/SentencePackPanel/);
    expect(body).toMatch(/ObserveEasePanel/);
    expect(body).not.toMatch(/Visual Rule Builder/i);
    expect(body).not.toMatch(/full-page builder/i);
    expect(body).not.toMatch(/book a demo/i);
    expect(body).not.toMatch(/start free/i);
  });
});
