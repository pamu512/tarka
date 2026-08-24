import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import ForbiddenUnauthorized from "@/pages/ForbiddenUnauthorized";
import { leanHomePath } from "@/config/leanNav";

describe("ForbiddenUnauthorized", () => {
  it("sends the CTA to the lean home path instead of /dashboard", () => {
    render(
      <MemoryRouter>
        <ForbiddenUnauthorized />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /back to desk/i });
    expect(link).toHaveAttribute("href", leanHomePath());
    expect(link).not.toHaveAttribute("href", "/dashboard");
    expect(leanHomePath()).toBe("/decisions");
    expect(link).toHaveAttribute("href", "/decisions");
    const signIn = screen.getByRole("link", { name: /sign in/i });
    expect(signIn).toHaveAttribute("href", "/login");
  });
});
