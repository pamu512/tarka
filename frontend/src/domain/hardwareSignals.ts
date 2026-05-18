/**
 * Client-side hardware / instrument signal maps for visual diffing (live transactions, audits).
 * Keys are dotted paths after flattening nested device payloads.
 */

export type HardwareSignalMap = Record<string, string>;

export type HardwareSimilarityResult = {
  /** Fraction of comparable keys (present in both with non-empty values) that match exactly. */
  ratio: number;
  comparableKeys: string[];
  matchingKeys: Set<string>;
};

function isScalar(v: unknown): v is string | number | boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return true;
  return false;
}

/** Flatten nested objects into dotted keys; arrays skipped (not comparable as scalar). */
export function flattenHardwareSignals(root: unknown, prefix = ""): HardwareSignalMap {
  if (root === null || root === undefined) return {};
  if (Array.isArray(root)) return {};
  if (typeof root !== "object") return {};
  const out: HardwareSignalMap = {};
  for (const [k, v] of Object.entries(root as Record<string, unknown>)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (isScalar(v)) {
      const s = String(v).trim();
      if (s) out[key] = s;
    } else if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(out, flattenHardwareSignals(v, key));
    }
  }
  return out;
}

/**
 * Pull hardware-shaped subtrees from a transaction / audit payload.
 * Convention: `hardware_signals`, `hardwareSignals`, nested `device_context`, `instrument`.
 */
export function extractHardwareSignalsFromPayload(o: Record<string, unknown>): HardwareSignalMap {
  const merged: HardwareSignalMap = {};

  const direct =
    (readRecord(o.hardware_signals) ?? readRecord(o.hardwareSignals)) ?? null;
  if (direct) Object.assign(merged, flattenHardwareSignals(direct));

  const device = readRecord(o.device_context) ?? readRecord(o.deviceContext);
  if (device) Object.assign(merged, flattenHardwareSignals(device));

  const instrument = readRecord(o.instrument) ?? readRecord(o.device);
  if (instrument) Object.assign(merged, flattenHardwareSignals(instrument));

  if (Object.keys(merged).length === 0) {
    const fallback = readRecord(o.payload);
    if (fallback) {
      const hw = readRecord(fallback.hardware) ?? readRecord(fallback.device);
      if (hw) Object.assign(merged, flattenHardwareSignals(hw));
    }
  }

  return merged;
}

function readRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** Similarity over keys present in both maps with non-empty values. */
export function hardwareSimilarityRatio(a: HardwareSignalMap, b: HardwareSignalMap): HardwareSimilarityResult {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const comparable: string[] = [];
  for (const k of keys) {
    const va = a[k]?.trim();
    const vb = b[k]?.trim();
    if (va && vb) comparable.push(k);
  }
  if (comparable.length === 0) {
    return { ratio: 0, comparableKeys: [], matchingKeys: new Set() };
  }
  const matchingKeys = new Set<string>();
  let matches = 0;
  for (const k of comparable) {
    if (a[k] === b[k]) {
      matches++;
      matchingKeys.add(k);
    }
  }
  return {
    ratio: matches / comparable.length,
    comparableKeys: comparable.sort(),
    matchingKeys,
  };
}

export const VISUAL_DIFF_HIGHLIGHT_THRESHOLD = 0.8;
