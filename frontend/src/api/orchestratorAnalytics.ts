/**
 * Orchestrator analytical transaction stream — DuckDB / ClickHouse via
 * ``GET /v1/analytics/transactions`` (dev proxy: ``/api/orchestrator``).
 */

export type AnalyticsTransactionWireRow = Record<string, unknown>;

export type AnalyticsTransactionsPageResponse = {
  rows: AnalyticsTransactionWireRow[];
  next_cursor: string | null;
  query_ms: number | null;
  backend: string | null;
};

export type AnalyticsTransactionsQuery = {
  limit?: number;
  cursor?: string | null;
  signal?: AbortSignal;
};

const BASE = "/api/orchestrator/v1/analytics/transactions";

const IS_PRODUCTION_BUILD = import.meta.env.PROD === true;
const MOCK_MODE = ((import.meta.env.VITE_USE_API_MOCKS as string | undefined) ?? "auto").trim().toLowerCase();
const USE_API_MOCKS =
  !IS_PRODUCTION_BUILD && (MOCK_MODE === "true" || (MOCK_MODE !== "false" && import.meta.env.DEV));

export async function fetchAnalyticsTransactionsPage(
  opts: AnalyticsTransactionsQuery = {},
): Promise<AnalyticsTransactionsPageResponse> {
  const q = new URLSearchParams();
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.cursor) q.set("cursor", opts.cursor);
  const url = q.size ? `${BASE}?${q}` : BASE;

  if (USE_API_MOCKS) {
    const { getMockResponse } = await import("./mockData");
    const mock = getMockResponse(url, { method: "GET" });
    if (mock !== null) {
      const body = mock as AnalyticsTransactionsPageResponse;
      return {
        rows: Array.isArray(body.rows) ? body.rows : [],
        next_cursor: body.next_cursor ?? null,
        query_ms: typeof body.query_ms === "number" ? body.query_ms : null,
        backend: typeof body.backend === "string" ? body.backend : "duckdb",
      };
    }
  }

  const res = await fetch(url, {
    headers: { Accept: "application/json" },
    signal: opts.signal,
  });
  const text = await res.text();
  if (!res.ok) {
    if (USE_API_MOCKS) {
      const { getMockResponse } = await import("./mockData");
      const mock = getMockResponse(url, { method: "GET" });
      if (mock !== null) {
        const body = mock as AnalyticsTransactionsPageResponse;
        return {
          rows: Array.isArray(body.rows) ? body.rows : [],
          next_cursor: body.next_cursor ?? null,
          query_ms: typeof body.query_ms === "number" ? body.query_ms : null,
          backend: typeof body.backend === "string" ? body.backend : "duckdb",
        };
      }
    }
    throw new Error(text || `Analytics transactions ${res.status}`);
  }
  const body = JSON.parse(text) as AnalyticsTransactionsPageResponse;
  return {
    rows: Array.isArray(body.rows) ? body.rows : [],
    next_cursor: body.next_cursor ?? null,
    query_ms: typeof body.query_ms === "number" ? body.query_ms : null,
    backend: typeof body.backend === "string" ? body.backend : null,
  };
}
