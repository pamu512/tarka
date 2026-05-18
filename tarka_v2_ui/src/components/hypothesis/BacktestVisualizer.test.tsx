/** @vitest-environment jsdom */

import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { BacktestVisualizer } from "./BacktestVisualizer";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="recharts-mock">{children}</div>
  ),
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Area: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));

const sampleSeries = [
  {
    bucket: "2026-05-18 10:00:00",
    label: "May 18, 10 AM",
    production_blocks: 3,
    shadow_blocks: 12,
    shadow_only_blocks: 9,
  },
  {
    bucket: "2026-05-18 11:00:00",
    label: "May 18, 11 AM",
    production_blocks: 2,
    shadow_blocks: 18,
    shadow_only_blocks: 16,
  },
];

describe("BacktestVisualizer", () => {
  afterEach(() => {
    cleanup();
  });

  it("gate 198: renders overlay chart and shadow-only attack wave total", () => {
    render(<BacktestVisualizer series={sampleSeries} />);
    expect(screen.getByTestId("backtest-visualizer")).toBeTruthy();
    expect(screen.getByTestId("backtest-shadow-only-total").textContent).toContain("25");
    expect(screen.getByTestId("recharts-mock")).toBeTruthy();
  });

  it("shows empty state without series", () => {
    render(<BacktestVisualizer series={[]} />);
    expect(screen.getByTestId("backtest-visualizer-empty")).toBeTruthy();
  });
});
