import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionTokens, clearSessionTokens } from "@/api/authSession";
import { RequireRole } from "@/components/rbac/RequireRole";

function encodeTestJwt(payload: Record<string, unknown>): string {
  const enc = (obj: object): string =>
    btoa(JSON.stringify(obj))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${enc({ alg: "none", typ: "JWT" })}.${enc(payload)}.sig`;
}

describe("RequireRole", () => {
  beforeEach(() => {
    clearSessionTokens();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    cleanup();
    clearSessionTokens();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("renders children when JWT roles claim includes the required role exactly", () => {
    setSessionTokens(encodeTestJwt({ sub: "u1", roles: ["RiskArchitect"] }), null);
    render(
      <MemoryRouter initialEntries={["/rules/visual"]}>
        <Routes>
          <Route
            path="/rules/visual"
            element={
              <RequireRole allow="RiskArchitect">
                <div>builder</div>
              </RequireRole>
            }
          />
          <Route path="/403-unauthorized" element={<div>forbidden</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("builder")).toBeInTheDocument();
    expect(screen.queryByText("forbidden")).not.toBeInTheDocument();
  });

  it("redirects a FraudAnalyst JWT to /403-unauthorized for a RiskArchitect route and logs a structured warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    setSessionTokens(encodeTestJwt({ sub: "u1", roles: ["FraudAnalyst"] }), null);
    render(
      <MemoryRouter initialEntries={["/rules/visual"]}>
        <Routes>
          <Route
            path="/rules/visual"
            element={
              <RequireRole allow="RiskArchitect">
                <div>builder</div>
              </RequireRole>
            }
          />
          <Route path="/403-unauthorized" element={<div>forbidden</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.queryByText("builder")).not.toBeInTheDocument();
    expect(screen.getByText("forbidden")).toBeInTheDocument();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      "[RBAC]",
      "route access denied",
      expect.objectContaining({
        attemptedPath: "/rules/visual",
        requiredRoles: ["RiskArchitect"],
        rolesFromJwt: ["FraudAnalyst"],
        reason: "role_denied",
      }),
    );
  });

  it("reads roles from a custom OIDC claim when VITE_OIDC_ROLES_CLAIM is set", () => {
    vi.stubEnv("VITE_OIDC_ROLES_CLAIM", "tarka_roles");
    setSessionTokens(encodeTestJwt({ sub: "u1", tarka_roles: ["RiskArchitect"] }), null);
    render(
      <MemoryRouter initialEntries={["/rules/visual"]}>
        <Routes>
          <Route
            path="/rules/visual"
            element={
              <RequireRole allow="RiskArchitect">
                <div>builder</div>
              </RequireRole>
            }
          />
          <Route path="/403-unauthorized" element={<div>forbidden</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("builder")).toBeInTheDocument();
  });

  it("denies access when there is no access token and logs no_access_token", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <MemoryRouter initialEntries={["/rules/visual"]}>
        <Routes>
          <Route
            path="/rules/visual"
            element={
              <RequireRole allow="RiskArchitect">
                <div>builder</div>
              </RequireRole>
            }
          />
          <Route path="/403-unauthorized" element={<div>forbidden</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("forbidden")).toBeInTheDocument();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      "[RBAC]",
      "route access denied",
      expect.objectContaining({
        reason: "no_access_token",
        rolesFromJwt: [],
      }),
    );
  });
});
