import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Help from "@/pages/Help";

describe("Help", () => {
  it("documents only lean production desk paths and does not claim prototype/synthetic fallback", () => {
    render(<Help />);
    expect(screen.getByRole("heading", { name: /help/i })).toBeInTheDocument();
    expect(screen.getAllByText("/cases").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/decisions").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/disputes").length).toBeGreaterThan(0);
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
    expect(body).not.toMatch(/Shadow/);
    expect(body).not.toMatch(/\/ops\/shadow/);
  });
});
