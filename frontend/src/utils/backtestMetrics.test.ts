import { describe, expect, it } from "vitest";
import { isTerminalBacktestStatus, mapBacktestMetricsToChartRows } from "./backtestMetrics";

describe("mapBacktestMetricsToChartRows", () => {
  it("maps chart_series from job metrics", () => {
    const rows = mapBacktestMetricsToChartRows({
      chart_series: [
        { chunk_index: 0, rows_processed: 1000, false_positive_rate: 0.1, precision: 0.8, recall: 0.7 },
        { chunk_index: 1, rows_processed: 2000, false_positive_rate: 0.09, precision: 0.82, recall: 0.71 },
      ],
    });
    expect(rows).toHaveLength(2);
    expect(rows[0].false_positive_rate).toBeCloseTo(0.1);
    expect(rows[1].recall).toBeCloseTo(0.71);
  });

  it("falls back to aggregate metrics when chart_series missing", () => {
    const rows = mapBacktestMetricsToChartRows({
      rows_processed: 500,
      false_positive_rate: 0.05,
      precision: 0.9,
      recall: 0.6,
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("Final");
    expect(rows[0].precision).toBeCloseTo(0.9);
  });

  it("returns empty for invalid input", () => {
    expect(mapBacktestMetricsToChartRows(null)).toEqual([]);
    expect(mapBacktestMetricsToChartRows({})).toEqual([]);
  });
});

describe("isTerminalBacktestStatus", () => {
  it("detects terminal states", () => {
    expect(isTerminalBacktestStatus("SUCCEEDED")).toBe(true);
    expect(isTerminalBacktestStatus("FAILED_TIMEOUT")).toBe(true);
    expect(isTerminalBacktestStatus("PENDING")).toBe(false);
  });
});
