import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionTokens, getAccessToken, getRefreshToken } from "@/api/authSession";
import OidcCallback from "@/pages/OidcCallback";

describe("OidcCallback", () => {
  beforeEach(() => {
    clearSessionTokens();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearSessionTokens();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("redeems the ticket, stores tokens, and navigates to next", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "access-from-idp",
          refresh_token: "refresh-from-idp",
          next: "/rules/visual",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/auth/callback?ticket=one-time"]}>
        <Routes>
          <Route path="/auth/callback" element={<OidcCallback />} />
          <Route path="/rules/visual" element={<div>visual-builder</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("visual-builder")).toBeInTheDocument();
    expect(getAccessToken()).toBe("access-from-idp");
    expect(getRefreshToken()).toBe("refresh-from-idp");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ ticket: "one-time" }),
      }),
    );
  });

  it("shows an error when the ticket is missing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/auth/callback"]}>
        <Routes>
          <Route path="/auth/callback" element={<OidcCallback />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toMatch(/missing one-time ticket/i);
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getAccessToken()).toBeNull();
  });
});

