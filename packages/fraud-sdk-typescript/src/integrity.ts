/**
 * In-transit integrity: SHA-256 over canonical unified-signal JSON (wire keys **except** ``n`` and
 * ``ih``) plus ``|`` + ``session_nonce`` (server-issued at page load). Matches
 * ``signal_api.transit_integrity`` / ``tarka_v2_core.schemas.ingestion.UnifiedSignalSchema``.
 */

/** Wire JSON keys use bandwidth aliases (``ch``, ``sid``, …) as sent to ``POST /v1/signals/ingest``. */
export type UnifiedSignalWireForHash = Record<string, unknown>;

/**
 * Deterministic JSON: sorted keys, no spaces, **excluding** ``n`` and ``ih`` so the hash matches
 * Python ``json.dumps(..., sort_keys=True, separators=(',', ':'))`` on the same logical payload.
 */
export function canonicalUnifiedSignalJsonExcludingNonce(
  wirePayload: UnifiedSignalWireForHash,
): string {
  const { n: _n, ih: _ih, gc: _gc, gct: _gct, ...rest } = wirePayload;
  const sorted: Record<string, unknown> = {};
  for (const k of Object.keys(rest).sort()) {
    sorted[k] = rest[k];
  }
  return JSON.stringify(sorted);
}

/** SHA-256 hex (lowercase) of UTF-8 ``canonical + '|' + sessionNonce``. */
export async function computeInTransitIntegrityHash(
  wirePayload: UnifiedSignalWireForHash,
  sessionNonce: string,
): Promise<string> {
  const canonical = canonicalUnifiedSignalJsonExcludingNonce(wirePayload);
  const input = `${canonical}|${sessionNonce}`;
  const buf = new TextEncoder().encode(input);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Merge ``n`` (nonce) and ``ih`` (integrity hash) onto the wire payload for ingest. */
export async function attachInTransitIntegrityFields(
  wirePayload: UnifiedSignalWireForHash,
  sessionNonce: string,
): Promise<UnifiedSignalWireForHash> {
  const { n: _n, ih: _ih, ...base } = wirePayload;
  const ih = await computeInTransitIntegrityHash(base, sessionNonce);
  return { ...base, n: sessionNonce, ih };
}
