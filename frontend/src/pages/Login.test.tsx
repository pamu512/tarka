import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Login from "@/pages/Login";

describe("Login", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows local-mode copy when oidc is disabled and does not link to an IdP", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ oidc_enabled: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/local mode/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign in with sso/i })).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").toMatch(/ALLOW_INSECURE_NO_AUTH/);
  });

  it("shows an SSO button that starts the BFF login with next=", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ oidc_enabled: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(
      <MemoryRouter initialEntries={["/login?next=/rules/visual"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: /sign in with sso/i });
    expect(link).toHaveAttribute("href", "/api/auth/login?next=%2Frules%2Fvisual");
  });

  it("surfaces a 503 when issuer is set without a client id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "OIDC_ISSUER is set but OIDC_CLIENT_ID is empty" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toMatch(/OIDC_CLIENT_ID/);
    });
    expect(screen.queryByRole("link", { name: /sign in with sso/i })).not.toBeInTheDocument();
  });
});

