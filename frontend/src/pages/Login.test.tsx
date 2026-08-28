import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    expect(screen.getByTestId("local-analyst-key")).toBeInTheDocument();
    expect(document.body.textContent ?? "").toMatch(/desk-analyst-local/);
    expect(document.body.textContent ?? "").not.toMatch(/VITE_API_KEY/);
  });

  it("stores a pasted seed key as a session-only analyst login", async () => {
    const { setDeskAnalystApiKey, getDeskAnalystApiKey, clearDeskAnalystApiKey } = await import(
      "@/api/deskAnalystSession"
    );
    clearDeskAnalystApiKey();
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
      <MemoryRouter initialEntries={["/login?next=/decisions"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/decisions" element={<div>decisions-home</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const input = await screen.findByTestId("local-analyst-key");
    fireEvent.change(input, { target: { value: "desk-analyst-local" } });
    fireEvent.click(screen.getByTestId("local-analyst-submit"));
    expect(getDeskAnalystApiKey()).toBe("desk-analyst-local");
    expect(await screen.findByText("decisions-home")).toBeInTheDocument();
    setDeskAnalystApiKey("");
  });

  it("clears a pasted key when continuing as viewer", async () => {
    const { setDeskAnalystApiKey, getDeskAnalystApiKey } = await import("@/api/deskAnalystSession");
    setDeskAnalystApiKey("wrong-key");
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
      <MemoryRouter initialEntries={["/login?next=/decisions"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/decisions" element={<div>decisions-home</div>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("local-viewer-continue"));
    expect(getDeskAnalystApiKey()).toBeNull();
    expect(await screen.findByText("decisions-home")).toBeInTheDocument();
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

