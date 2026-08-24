import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import PlaneOff from "@/pages/PlaneOff";
import { leanHomePath } from "@/config/leanNav";

describe("PlaneOff", () => {
  it("states graph plane off without productizing a 503", () => {
    render(
      <MemoryRouter>
        <PlaneOff plane="graph" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: /graph plane off/i })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/plane off/i);
    expect(document.body.textContent ?? "").not.toMatch(/503/);
    expect(document.body.textContent ?? "").not.toMatch(/coming soon/i);
    const back = screen.getByRole("link", { name: /back to desk/i });
    expect(back).toHaveAttribute("href", leanHomePath());
    expect(back).toHaveAttribute("href", "/decisions");
    expect(back).not.toHaveAttribute("href", "/cases");
  });

  it("states Advise plane off", () => {
    render(
      <MemoryRouter>
        <PlaneOff plane="advise" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: /advise plane off/i })).toBeInTheDocument();
  });
});
