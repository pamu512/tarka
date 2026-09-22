import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";

import { PackJourneyTabs } from "./PackJourneyTabs";

// react-router's NavLink needs a router ancestor; MemoryRouter provides it.
vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return actual;
});

const STAGES = ["author", "observe", "backtest", "promote", "monitor"];

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PackJourneyTabs />
    </MemoryRouter>,
  );
}

describe("PackJourneyTabs", () => {
  it.each(STAGES.map((s, i) => [s, ["/rules", "/observe", "/ops/backtest", "/ops/shadow", "/analytics/rule-performance"][i]] as const))(
    "renders all five journey stages from %s (%s)",
    (stage, path) => {
      renderAt(path);
      for (const label of ["Author", "Observe", "Backtest", "Promote", "Monitor"]) {
        expect(screen.getByRole("link", { name: new RegExp(label, "i") })).toBeTruthy();
      }
    },
  );

  it("marks the active stage by current path", () => {
    renderAt("/ops/backtest");
    const backtest = screen.getByRole("link", { name: /backtest/i });
    expect(backtest.className).toMatch(/brand|active/i);
    const author = screen.getByRole("link", { name: /author/i });
    expect(author.className).not.toMatch(/brand-600|active/i);
  });

  it("links go to the five real surfaces, not new routes", () => {
    renderAt("/rules");
    expect(screen.getByRole("link", { name: /author/i }).getAttribute("href")).toBe("/rules");
    expect(screen.getByRole("link", { name: /observe/i }).getAttribute("href")).toBe("/observe");
    expect(screen.getByRole("link", { name: /backtest/i }).getAttribute("href")).toBe("/ops/backtest");
    expect(screen.getByRole("link", { name: /promote/i }).getAttribute("href")).toBe("/ops/shadow");
    expect(screen.getByRole("link", { name: /monitor/i }).getAttribute("href")).toBe("/analytics/rule-performance");
  });
});
