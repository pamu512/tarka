/**
 * Minimal Prometheus exposition parser for in-browser infra dashboards.
 * Extracts sample totals and notable counters (queue / load / ingest).
 */

export type PrometheusDigest = {
  /** Sum of all `http_requests_total` samples (traffic proxy). */
  httpRequestsTotal: number;
  /** Sum of `http_server_errors_total`. */
  httpServerErrorsTotal: number;
  /** Named counters excluding http_* histogram parts. */
  notableCounters: Array<{ name: string; value: number }>;
};

const NOTABLE = /(queue|depth|shedding|ingest|worker|pending|backlog|nats|redis)/i;

function parseSampleLine(line: string): { name: string; value: number } | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#")) return null;
  const brace = trimmed.indexOf("{");
  if (brace === -1) {
    const sp = trimmed.lastIndexOf(" ");
    if (sp <= 0) return null;
    const name = trimmed.slice(0, sp).trim();
    const value = Number(trimmed.slice(sp + 1).trim());
    if (!name || Number.isNaN(value)) return null;
    return { name, value };
  }
  const name = trimmed.slice(0, brace).trim();
  const close = trimmed.indexOf("}", brace);
  if (close < 0) return null;
  const rest = trimmed.slice(close + 1).trim();
  const parts = rest.split(/\s+/);
  if (parts.length < 1) return null;
  const value = Number(parts[parts.length - 1]);
  if (!name || Number.isNaN(value)) return null;
  return { name, value };
}

export function parsePrometheusText(text: string): PrometheusDigest {
  let httpRequestsTotal = 0;
  let httpServerErrorsTotal = 0;
  const notableMap = new Map<string, number>();

  for (const line of text.split("\n")) {
    const parsed = parseSampleLine(line);
    if (!parsed) continue;
    const { name, value } = parsed;
    if (name === "http_requests_total") {
      httpRequestsTotal += value;
      continue;
    }
    if (name === "http_server_errors_total") {
      httpServerErrorsTotal += value;
      continue;
    }
    if (name.startsWith("http_")) continue;
    if (NOTABLE.test(name)) {
      notableMap.set(name, (notableMap.get(name) ?? 0) + value);
    }
  }

  const notableCounters = [...notableMap.entries()]
    .map(([n, v]) => ({ name: n, value: v }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);

  return { httpRequestsTotal, httpServerErrorsTotal, notableCounters };
}
