import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TenantEnvironmentProvider } from "../context/TenantEnvironmentContext";
import NatsSetuMonitor from "./NatsSetuMonitor";

function wrap(ui: ReactElement) {
  return (
    <MemoryRouter>
      <TenantEnvironmentProvider>{ui}</TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

describe("NatsSetuMonitor", () => {
  it("renders VPN, email, and phone lane cards from mock API", async () => {
    render(wrap(<NatsSetuMonitor />));
    await waitFor(() => {
      expect(screen.getByTestId("nats-setu-channel-vpn_ip")).toBeInTheDocument();
    });
    expect(screen.getByTestId("nats-setu-channel-email")).toBeInTheDocument();
    expect(screen.getByTestId("nats-setu-channel-phone")).toBeInTheDocument();
    expect(screen.getByText(/NATS connected/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Email reputation" })).toBeInTheDocument();
  });
});
