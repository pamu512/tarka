import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Help from "@/pages/Help";

describe("Help", () => {
  it("documents only lean production desk paths and does not claim prototype/synthetic fallback", () => {
    render(<Help />);
    expect(screen.getByRole("heading", { name: /help/i })).toBeInTheDocument();
    expect(screen.getAllByText("/cases").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/decisions").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/disputes/:id").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/help").length).toBeGreaterThan(0);
    expect(screen.getByText(/plane off/i)).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/coming soon/i);
    const body = document.body.textContent ?? "";
    expect(body.toLowerCase()).not.toMatch(/prototype/);
    expect(body.toLowerCase()).not.toMatch(/synthetic data/);
    expect(body).not.toMatch(/Investigation Copilot/);
    expect(body).not.toMatch(/OSINT/);
    expect(body).not.toMatch(/Admin Panel/);
    expect(body).not.toMatch(/Simulation/);
  });


  it("points no-code at SentencePackPanel + ObserveEasePanel, not VisualRuleBuilder as a SKU", () => {
    render(<Help />);
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/SentencePackPanel/);
    expect(body).toMatch(/ObserveEasePanel/);
    expect(body).toMatch(/not a product SKU/i);
    expect(body).not.toMatch(/Visual Rule Builder/i);
    expect(body).not.toMatch(/full-page builder/i);
    expect(body).not.toMatch(/book a demo/i);
    expect(body).not.toMatch(/start free/i);
  });

  it("explains the investigator path in plain English", () => {
    render(<Help />);
    const section = document.getElementById("leftovers");
    expect(section).toBeTruthy();
    const copy = section?.textContent ?? "";
    expect(copy).toMatch(/open receipt/i);
    expect(copy).toMatch(/pack fired|which pack/i);
    expect(copy).toMatch(/Create Observe draft/i);
    expect(copy).toMatch(/not a case CRM|not your case CRM/i);
    expect(copy).toMatch(/do not need to memorize pack UUIDs/i);
  });
});
