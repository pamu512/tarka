import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionTokens, setSessionTokens } from "@/api/authSession";
import * as client from "@/api/client";
import { TarkaRbacRole } from "@/security/rbacConstants";

vi.mock("@/config/leanNav", () => ({ DESK_PROFILE: "product" }));

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    fields: {
      list: vi.fn(),
      maps: vi.fn(),
      upsert: vi.fn(),
      putMap: vi.fn(),
      discover: vi.fn(),
    },
  };
});

import { FieldMapPanel } from "./FieldMapPanel";

function encodeTestJwt(payload: Record<string, unknown>): string {
  const enc = (obj: object): string =>
    btoa(JSON.stringify(obj))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${enc({ alg: "none", typ: "JWT" })}.${enc(payload)}.sig`;
}

function renderPanel(ui: ReactElement = <FieldMapPanel tenantId="t1" />) {
  return render(
    <MemoryRouter initialEntries={["/rules"]}>
      <Routes>
        <Route path="/rules" element={ui} />
        <Route path="/login" element={<div data-testid="login-page">login</div>} />
        <Route path="/403-unauthorized" element={<div data-testid="forbidden-page">forbidden</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function expectStayedOnRules() {
  expect(screen.queryByTestId("login-page")).toBeNull();
  expect(screen.queryByTestId("forbidden-page")).toBeNull();
}

describe("FieldMapPanel (product)", () => {
  beforeEach(() => {
    clearSessionTokens();
    setSessionTokens(encodeTestJwt({ sub: "u1", roles: [TarkaRbacRole.RiskArchitect] }), null);

    vi.mocked(client.fields.list).mockReset();
    vi.mocked(client.fields.maps).mockReset();
    vi.mocked(client.fields.upsert).mockReset();
    vi.mocked(client.fields.putMap).mockReset();
    vi.mocked(client.fields.discover).mockReset();

    vi.mocked(client.fields.list).mockResolvedValue([
      { name: "amount", explanation: "transaction amount", source: "tarka_core" },
    ]);
    vi.mocked(client.fields.maps).mockResolvedValue([]);
    vi.mocked(client.fields.upsert).mockResolvedValue({
      name: "order_channel",
      explanation: "who sold",
      source: "new_feature",
    });
    vi.mocked(client.fields.putMap).mockResolvedValue({
      tenant_id: "t1",
      buyer_key: "txn_amt",
      registry_name: "amount",
    });
    vi.mocked(client.fields.discover).mockResolvedValue({
      already_named: ["amount"],
      mapped: [],
      candidates: [{ buyer_key: "order_channel", suggested_source: "new_feature" }],
    });
  });

  afterEach(() => {
    clearSessionTokens();
  });

  it("shows panel on product", async () => {
    renderPanel();
    expect(await screen.findByTestId("field-map-panel")).toBeTruthy();
    expectStayedOnRules();
  });

  it("hides without navigating when JWT is FraudAnalyst", async () => {
    clearSessionTokens();
    setSessionTokens(encodeTestJwt({ sub: "u1", roles: [TarkaRbacRole.FraudAnalyst] }), null);
    renderPanel();
    expect(screen.queryByTestId("field-map-panel")).toBeNull();
    expectStayedOnRules();
    await waitFor(() => {
      expect(client.fields.list).not.toHaveBeenCalled();
      expect(client.fields.maps).not.toHaveBeenCalled();
    });
  });

  it("hides without navigating when there is no token", async () => {
    clearSessionTokens();
    renderPanel();
    expect(screen.queryByTestId("field-map-panel")).toBeNull();
    expectStayedOnRules();
    await waitFor(() => {
      expect(client.fields.list).not.toHaveBeenCalled();
      expect(client.fields.maps).not.toHaveBeenCalled();
    });
  });

  it("lists seed name amount", async () => {
    renderPanel();
    expect(await screen.findByText("amount")).toBeInTheDocument();
    expect(client.fields.list).toHaveBeenCalledWith("t1");
    expect(client.fields.maps).toHaveBeenCalledWith("t1");
  });

  it("discover shows candidate", async () => {
    renderPanel();
    await screen.findByTestId("field-map-panel");
    fireEvent.change(screen.getByTestId("field-map-payload"), {
      target: { value: '{"order_channel":"web"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: /discover/i }));
    expect(await screen.findByText("order_channel")).toBeInTheDocument();
    expect(client.fields.discover).toHaveBeenCalledWith({
      tenant_id: "t1",
      payload: { order_channel: "web" },
    });
  });

  it("upserts new_feature from candidate explanation", async () => {
    renderPanel();
    await screen.findByTestId("field-map-panel");
    fireEvent.change(screen.getByTestId("field-map-payload"), {
      target: { value: '{"order_channel":"web"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: /discover/i }));
    await screen.findByText("order_channel");
    fireEvent.change(screen.getByTestId("field-map-explanation-order_channel"), {
      target: { value: "who sold" },
    });
    fireEvent.click(screen.getByTestId("field-map-apply-order_channel"));
    await waitFor(() => {
      expect(client.fields.upsert).toHaveBeenCalledWith("t1", "order_channel", {
        explanation: "who sold",
        source: "new_feature",
      });
    });
    expect(client.fields.putMap).not.toHaveBeenCalled();
  });

  it("putMap when candidate maps to existing name", async () => {
    renderPanel();
    await screen.findByTestId("field-map-panel");
    fireEvent.change(screen.getByTestId("field-map-payload"), {
      target: { value: '{"txn_amt":9}' },
    });
    vi.mocked(client.fields.discover).mockResolvedValue({
      already_named: [],
      mapped: [],
      candidates: [{ buyer_key: "txn_amt", suggested_source: "new_feature" }],
    });
    fireEvent.click(screen.getByRole("button", { name: /discover/i }));
    await screen.findByText("txn_amt");
    fireEvent.change(screen.getByTestId("field-map-map-to-txn_amt"), {
      target: { value: "amount" },
    });
    fireEvent.click(screen.getByTestId("field-map-apply-txn_amt"));
    await waitFor(() => {
      expect(client.fields.putMap).toHaveBeenCalledWith({
        tenant_id: "t1",
        buyer_key: "txn_amt",
        registry_name: "amount",
      });
    });
    expect(client.fields.upsert).not.toHaveBeenCalled();
  });
});
