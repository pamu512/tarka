export type VerticalBenchmarkHistoryEntry = {
  ts: string;
  scenario: string;
  vertical: string;
  baseline_f1: number;
  vertical_f1: number;
  delta_f1: number;
};

const MAX_ENTRIES = 20;
let entries: VerticalBenchmarkHistoryEntry[] = [];

export function getVerticalBenchmarkHistory(): VerticalBenchmarkHistoryEntry[] {
  return [...entries];
}

export function prependVerticalBenchmarkHistory(
  entry: VerticalBenchmarkHistoryEntry,
): VerticalBenchmarkHistoryEntry[] {
  entries = [entry, ...entries].slice(0, MAX_ENTRIES);
  return getVerticalBenchmarkHistory();
}

export function resetVerticalBenchmarkHistoryForTests(): void {
  entries = [];
}
