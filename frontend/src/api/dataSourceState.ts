/** Tracks whether recent API traffic used live backends or mock fallbacks (for analyst trust UI). */

export type DataOutcome = "live" | "mock" | "offline";

type Listener = () => void;

let lastOutcome: DataOutcome = "live";
let lastUpdatedAt = Date.now();
const listeners = new Set<Listener>();

export function reportDataOutcome(outcome: DataOutcome) {
  lastOutcome = outcome;
  lastUpdatedAt = Date.now();
  listeners.forEach((fn) => fn());
}

export function getDataSourceSnapshot(): { outcome: DataOutcome; updatedAt: number } {
  return { outcome: lastOutcome, updatedAt: lastUpdatedAt };
}

export function subscribeDataSource(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
