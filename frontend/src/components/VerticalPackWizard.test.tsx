import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { VerticalPackWizard } from "./VerticalPackWizard";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    rules: {
      ...actual.rules,
      verticalPacks: vi.fn(),
      installVerticalPack: vi.fn(),
    },
    simulation: {
      ...actual.simulation,
      benchmarkVertical: vi.fn(),
    },
  };
});

const CATALOG = {
  fintech: { name: "Fintech", rules: 8, version: 1, has_kill_criteria: true },
  gaming: { name: "Gaming", rules: 6, version: 1, has_kill_criteria: true },
};

const FULL = {
  id: "fintech",
  name: "Fintech",
  version: 1,
  rules: [
    { id: "r1", when: { field: "amount", op: "gte", value: 5000 }, score_delta: 30 },
    { id: "r2", when: { field: "account_age_days", op: "lte", value: 2 }, score_delta: 20 },
  ],
  tag_rules: [],
  kill_criteria: { min_precision: 0.5 },
};

describe("VerticalPackWizard", () => {
  beforeEach(() => {
    vi.mocked(client.rules.verticalPacks).mockReset();
    vi.mocked(client.rules.installVerticalPack).mockReset();
    vi.mocked(client.simulation.benchmarkVertical).mockReset();
    vi.mocked(client.rules.verticalPacks).mockResolvedValue({
      vertical_packs: CATALOG,
    } as never);
  });

  it("lists catalog entries as selectable cards", async () => {
    render(<VerticalPackWizard onInstalled={() => {}} />);
    await screen.findByText(/fintech/i);
    expect(screen.getByText(/gaming/i)).toBeTruthy();
    expect(screen.getByText(/8 rules/i)).toBeTruthy();
  });

  it("previews full rules after selection", async () => {
    // full definition fetch goes through the same rules API surface
    vi.mocked(client.rules as never as { verticalPackDefinition: unknown }).verticalPackDefinition =
      vi.fn().mockResolvedValue(FULL);
    render(<VerticalPackWizard onInstalled={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /select.*fintech/i }));
    await screen.findByText(/amount/i);
    expect(screen.getByText(/account_age_days/i)).toBeTruthy();
    expect(screen.getByText(/kill criteria/i, { exact: false })).toBeTruthy();
  });

  it("runs benchmark then enables install, shows honest metrics", async () => {
    vi.mocked(client.rules as never as { verticalPackDefinition: unknown }).verticalPackDefinition =
      vi.fn().mockResolvedValue(FULL);
    vi.mocked(client.simulation.benchmarkVertical).mockResolvedValue({
      metrics: { precision: 0.82, recall: 0.61, f1_score: 0.7 },
    } as never);
    const onInstalled = vi.fn();
    render(<VerticalPackWizard onInstalled={onInstalled} />);
    fireEvent.click(await screen.findByRole("button", { name: /select.*fintech/i }));
    await screen.findByText(/amount/i);
    fireEvent.click(screen.getByRole("button", { name: /run benchmark/i }));
    await screen.findByText(/0.82/);
    const install = screen.getByRole("button", { name: /install/i });
    expect(install).toBeTruthy();
  });

  it("install requires benchmark first (honest gate copy)", async () => {
    vi.mocked(client.rules as never as { verticalPackDefinition: unknown }).verticalPackDefinition =
      vi.fn().mockResolvedValue(FULL);
    render(<VerticalPackWizard onInstalled={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /select.*fintech/i }));
    await screen.findByText(/amount/i);
    const install = screen.getByRole("button", { name: /install/i }) as HTMLButtonElement;
    expect(install.disabled).toBe(true);
    expect(screen.getByText(/benchmark first/i)).toBeTruthy();
  });
});
