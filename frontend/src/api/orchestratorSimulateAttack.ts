/**
 * POST ``/v1/demo/simulate_attack`` on the orchestrator (dev: Vite → ``/api/v1/demo/simulate_attack``).
 * Resolves only after the **entire** response is received (JSON body or NDJSON stream), so callers can
 * safely disable UI until the full result set is known.
 */

const IS_PRODUCTION_BUILD = import.meta.env.PROD === true;
const MOCK_MODE = ((import.meta.env.VITE_USE_API_MOCKS as string | undefined) ?? "auto").trim().toLowerCase();
const USE_API_MOCKS =
  !IS_PRODUCTION_BUILD && (MOCK_MODE === "true" || (MOCK_MODE !== "false" && import.meta.env.DEV));

function isNdjsonContentType(contentType: string): boolean {
  const ct = contentType.toLowerCase();
  return ct.includes("ndjson") || ct.includes("x-ndjson");
}

function extractResultsArray(body: unknown): unknown[] {
  if (!body || typeof body !== "object") return [];
  const o = body as Record<string, unknown>;
  const raw = o.results ?? o.items ?? o.outcomes;
  if (!Array.isArray(raw)) return [];
  return raw;
}

function assertCompleteSimulationPayload(body: unknown): { results: unknown[]; raw: unknown } {
  const results = extractResultsArray(body);
  if (results.length === 0) {
    throw new Error("Orchestrator returned no attack outcomes (empty results array)");
  }
  const o = body && typeof body === "object" ? (body as Record<string, unknown>) : null;
  const total = o && typeof o.total === "number" ? o.total : null;
  if (total != null && results.length !== total) {
    throw new Error(`Incomplete simulation: expected ${total} results, received ${results.length}`);
  }
  return { results, raw: body };
}

async function consumeNdjsonStreamToResults(res: Response): Promise<unknown[]> {
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("Simulate attack response has no body stream");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  const items: unknown[] = [];
  let expectedTotal: number | null = null;

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const payload = JSON.parse(trimmed) as Record<string, unknown>;
      if (typeof payload.total === "number") {
        expectedTotal = Math.max(expectedTotal ?? 0, payload.total);
      }
      if (payload.item != null && typeof payload.item === "object") {
        items.push(payload.item);
      } else if (typeof payload.transaction_id === "string") {
        items.push(payload);
      }
    }
  }

  const tail = buffer.trim();
  if (tail) {
    const payload = JSON.parse(tail) as Record<string, unknown>;
    if (typeof payload.total === "number") {
      expectedTotal = Math.max(expectedTotal ?? 0, payload.total);
    }
    if (payload.item != null && typeof payload.item === "object") {
      items.push(payload.item);
    } else if (typeof payload.transaction_id === "string") {
      items.push(payload);
    }
  }

  if (expectedTotal != null && items.length !== expectedTotal) {
    throw new Error(
      `Incomplete simulation stream: expected ${expectedTotal} outcomes, received ${items.length}`,
    );
  }
  if (items.length === 0) {
    throw new Error("Orchestrator returned no attack outcomes (empty NDJSON stream)");
  }
  return items;
}

/**
 * Resolves only after the orchestrator has returned the **complete** result set (JSON array or NDJSON stream).
 */
export async function postOrchestratorSimulateAttack(
  url: string = "/api/v1/demo/simulate_attack",
): Promise<{ results: unknown[]; raw: unknown }> {
  if (USE_API_MOCKS) {
    const { getMockResponse } = await import("./mockData");
    const mock = getMockResponse(url, { method: "POST", body: "{}" });
    if (mock !== null) {
      return assertCompleteSimulationPayload(mock);
    }
  }

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson, application/json",
    },
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) {
    if (USE_API_MOCKS) {
      const { getMockResponse } = await import("./mockData");
      const mock = getMockResponse(url, { method: "POST", body: "{}" });
      if (mock !== null) {
        return assertCompleteSimulationPayload(mock);
      }
    }
    const t = await res.text().catch(() => "");
    throw new Error(`Simulate attack failed (${res.status}): ${t.slice(0, 200)}`);
  }

  const contentType = res.headers.get("content-type") ?? "";

  if (isNdjsonContentType(contentType)) {
    const results = await consumeNdjsonStreamToResults(res);
    return { results, raw: { results, total: results.length, _format: "ndjson" } };
  }

  const json: unknown = await res.json();
  return assertCompleteSimulationPayload(json);
}
