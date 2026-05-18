/**
 * Hot-path browser telemetry → orchestrator ``POST /ingest`` (Redis / Anumana).
 * Does not touch the fraud graph; intended for Rust consumers draining Redis.
 */

export type TelemetryPacketV1 = { v: 1; enc: string; int: string };

/** Minimal device shape (structurally compatible with ``DeviceContext`` from ``index.ts``). */
export type AnumanaIngestDevice = {
  signals: {
    canvas_fp_hash: string | null;
    entropy_canvas_raster_digest?: string | null;
  };
  behavior?: { telemetry_packet?: TelemetryPacketV1 } | null;
};

/** JSON body for ``POST /ingest`` (snake_case matches FastAPI model). */
export type BrowserTelemetryIngestJson = {
  canvas_fingerprint: string | null;
  canvas_raster_digest_hex: string | null;
  ip: string | null;
  tenant_id: string | null;
  device_session_id: string | null;
  telemetry_packet: TelemetryPacketV1 | null;
};

/**
 * Map device signals (canvas / entropy + sealed behavior packet) into the ingest contract.
 * ``clientIp`` is optional: prefer server ``X-Forwarded-For`` when the SDK runs same-origin;
 * pass only when you have a trusted edge-reported IP.
 */
export function buildBrowserTelemetryIngestJson(
  device: AnumanaIngestDevice,
  opts?: {
    tenantId?: string | null;
    deviceSessionId?: string | null;
    /** Rare: only when a trusted edge exposes the client IP to the browser. */
    clientIp?: string | null;
  },
): BrowserTelemetryIngestJson {
  const s = device.signals;
  const raster = s.entropy_canvas_raster_digest ?? null;
  const canvasLegacy = s.canvas_fp_hash ?? null;
  const canvas = (raster && raster.length > 0 ? raster : canvasLegacy) ?? null;
  const pkt = device.behavior?.telemetry_packet;
  const packet: TelemetryPacketV1 | null =
    pkt && pkt.v === 1 && typeof pkt.enc === "string" && typeof pkt.int === "string"
      ? { v: 1, enc: pkt.enc, int: pkt.int }
      : null;

  return {
    canvas_fingerprint: canvas,
    canvas_raster_digest_hex: raster,
    ip: opts?.clientIp ?? null,
    tenant_id: opts?.tenantId ?? null,
    device_session_id: opts?.deviceSessionId ?? null,
    telemetry_packet: packet,
  };
}

export type PostBrowserTelemetryIngestOptions = {
  /** When ``ANUMANA_TELEMETRY_INGEST_KEY`` is set on the orchestrator. */
  apiKey?: string;
  signal?: AbortSignal;
  fetchFn?: typeof fetch;
};

/**
 * POST canvas / IP envelope + optional sealed packet to ``{baseUrl}/ingest``.
 * ``baseUrl`` should be the orchestrator origin (e.g. ``https://orch.example``).
 */
export async function postBrowserTelemetryIngest(
  orchestratorBaseUrl: string,
  body: BrowserTelemetryIngestJson,
  opts?: PostBrowserTelemetryIngestOptions,
): Promise<Response> {
  const base = orchestratorBaseUrl.replace(/\/$/, "");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts?.apiKey) {
    headers["X-Anumana-Ingest-Key"] = opts.apiKey;
  }
  const fetchImpl = opts?.fetchFn ?? fetch;
  return fetchImpl(`${base}/ingest`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
}

/** Convenience: build JSON from device snapshot and POST in one call. */
export async function flushDeviceContextToAnumana(
  orchestratorBaseUrl: string,
  device: AnumanaIngestDevice,
  opts?: PostBrowserTelemetryIngestOptions & {
    tenantId?: string | null;
    deviceSessionId?: string | null;
    clientIp?: string | null;
  },
): Promise<Response> {
  const json = buildBrowserTelemetryIngestJson(device, {
    tenantId: opts?.tenantId,
    deviceSessionId: opts?.deviceSessionId,
    clientIp: opts?.clientIp,
  });
  const { tenantId: _t, deviceSessionId: _d, clientIp: _c, ...rest } = opts ?? {};
  return postBrowserTelemetryIngest(orchestratorBaseUrl, json, rest);
}
