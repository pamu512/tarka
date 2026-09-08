import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { L2DraftButtons } from "./L2DraftButtons";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    rules: {
      ...actual.rules,
      createL2Draft: vi.fn(),
    },
  };
});

describe("L2DraftButtons", () => {
  beforeEach(() => {
    vi.mocked(client.rules.createL2Draft).mockReset();
    vi.mocked(client.rules.createL2Draft).mockResolvedValue({
      file: "l2_aaa.json",
      pack: { name: "l2_lo-1", mode: "shadow" },
    });
  });

  it("human Create draft skips backtest with actor reason", async () => {
    render(
      <L2DraftButtons leftoverId="lo-1" traceId="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" tenantId="acme" overrideWhy="known good" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    await waitFor(() => {
      expect(client.rules.createL2Draft).toHaveBeenCalledWith(
        expect.objectContaining({
          leftover_id: "lo-1",
          authored_by: "human",
          is_ai_authored: false,
          skip_backtest: true,
          skip_reason: "known good",
        }),
        "acme",
      );
    });
  });

  it("disables Create draft until typed why is at least 8 characters", async () => {
    render(
      <L2DraftButtons leftoverId="lo-1" traceId="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" tenantId="acme" />,
    );
    const create = screen.getByRole("button", { name: /create draft/i });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByTestId("leftover-override-why"), { target: { value: "short" } });
    expect(create).toBeDisabled();
    fireEvent.click(create);
    expect(client.rules.createL2Draft).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("leftover-override-why"), {
      target: { value: "seasonal spike" },
    });
    expect(create).toBeEnabled();
    fireEvent.click(create);
    await waitFor(() => {
      expect(client.rules.createL2Draft).toHaveBeenCalledWith(
        expect.objectContaining({
          leftover_id: "lo-1",
          override_why: "seasonal spike",
          skip_reason: "seasonal spike",
        }),
        "acme",
      );
    });
  });

  it("409 draft_exists shows open draft", async () => {
    vi.mocked(client.rules.createL2Draft).mockRejectedValue(
      new Error('409 {"code":"draft_exists","draft_id":"l2_lo-1","name":"l2_lo-1"}'),
    );
    render(
      <L2DraftButtons leftoverId="lo-1" traceId="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" tenantId="acme" />,
    );
    fireEvent.change(screen.getByTestId("leftover-override-why"), {
      target: { value: "known good leftover" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByTestId("open-existing-draft")).toHaveTextContent("Open draft l2_lo-1");
  });

  it("Author via BYO requires backtest (no skip)", async () => {
    render(
      <L2DraftButtons leftoverId="lo-1" traceId="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" tenantId="acme" />,
    );
    fireEvent.change(screen.getByTestId("leftover-override-why"), {
      target: { value: "known good leftover" },
    });
    fireEvent.click(screen.getByRole("button", { name: /author via byo/i }));
    await waitFor(() => {
      expect(client.rules.createL2Draft).toHaveBeenCalledWith(
        expect.objectContaining({
          authored_by: "scout",
          is_ai_authored: true,
          skip_backtest: false,
        }),
        "acme",
      );
    });
  });
});
