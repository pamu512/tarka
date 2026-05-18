import type { InferenceContext } from "../api/inferenceContext";

/** Circular distance between UTC hour indices [0,23]. */
export function utcHourDistance(a: number, b: number): number {
  const d = Math.abs(a - b);
  return Math.min(d, 24 - d);
}

/** UTC hour 0–23 from ISO timestamp (fallback: current hour in UTC). */
export function utcHourFromIso(iso: string | null | undefined): number {
  if (!iso || typeof iso !== "string") return new Date().getUTCHours();
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return new Date().getUTCHours();
  return new Date(t).getUTCHours();
}

function gaussianHourWeights(anchorHourUtc: number, sigma: number): number[] {
  return Array.from({ length: 24 }, (_, h) => {
    const dh = utcHourDistance(h, anchorHourUtc);
    return Math.exp(-(dh * dh) / (2 * sigma * sigma));
  });
}

/** Largest remainder so integers sum exactly to `total`. */
export function allocateIntegersFromWeights(weights: number[], total: number): number[] {
  if (weights.length === 0) return [];
  const sumW = weights.reduce((a, b) => a + b, 0);
  if (sumW <= 0 || total <= 0) return Array(weights.length).fill(0);
  const raw = weights.map((w) => (w / sumW) * total);
  const floors = raw.map((x) => Math.floor(x));
  const remainder = total - floors.reduce((a, b) => a + b, 0);
  const order = raw
    .map((x, i) => ({ i, frac: x - Math.floor(x) }))
    .sort((a, b) => b.frac - a.frac);
  const out = [...floors];
  for (let k = 0; k < remainder; k++) {
    out[order[k % order.length].i] += 1;
  }
  return out;
}

/**
 * When API omits hourly buckets, infer a 24-hour histogram from sliding-window totals.
 * Shape peaks near `anchorHourUtc`; sharpness rises when 5m density dominates 1h (acute burst).
 */
export function synthesizeHourlyVelocityBuckets(
  velocity5m: number,
  velocity1h: number,
  velocity24h: number,
  anchorHourUtc: number,
): number[] {
  const v24 = Math.max(0, Math.round(velocity24h));
  if (v24 === 0) return Array(24).fill(0);

  const v5 = Math.max(0, velocity5m);
  const v1 = Math.max(0, velocity1h);
  const burstRatio = Math.min(1, v5 / Math.max(1, v1));
  const sigma = 1.35 + (1 - burstRatio) * 7.25;

  const anchor = Number.isFinite(anchorHourUtc) ? (((anchorHourUtc % 24) + 24) % 24) : 14;
  const weights = gaussianHourWeights(anchor, sigma);
  return allocateIntegersFromWeights(weights, v24);
}

export function hourlyBucketsFromInference(inference: InferenceContext): number[] | null {
  const raw = inference.velocity_events_by_hour_utc;
  if (!Array.isArray(raw) || raw.length !== 24) return null;
  const out = raw.map((x) =>
    typeof x === "number" && Number.isFinite(x) ? Math.max(0, Math.round(x)) : 0,
  );
  return out.length === 24 ? out : null;
}

export type VelocityHeatmapModel = {
  buckets: number[];
  peakHourUtc: number | null;
  /** Sum of buckets (equals velocity_events_24h when synthesized exactly). */
  total: number;
  /** True when hourly buckets were inferred from 5m/1h/24h only. */
  synthesized: boolean;
};

export function buildVelocityHeatmapModel(
  inference: InferenceContext | null,
  anchorIso: string | null | undefined,
): VelocityHeatmapModel | null {
  if (!inference) return null;

  const fromApi = hourlyBucketsFromInference(inference);
  const anchorHour = utcHourFromIso(anchorIso ?? undefined);

  if (fromApi) {
    const total = fromApi.reduce((a, b) => a + b, 0);
    const peakHourUtc =
      total > 0
        ? fromApi.reduce((bestIdx, v, i, arr) => (v > arr[bestIdx] ? i : bestIdx), 0)
        : null;
    return {
      buckets: fromApi,
      peakHourUtc,
      total,
      synthesized: false,
    };
  }

  const buckets = synthesizeHourlyVelocityBuckets(
    inference.velocity_events_5m,
    inference.velocity_events_1h,
    inference.velocity_events_24h,
    anchorHour,
  );
  const total = buckets.reduce((a, b) => a + b, 0);
  const peakHourUtc =
    total > 0 ? buckets.reduce((bestIdx, v, i, arr) => (v > arr[bestIdx] ? i : bestIdx), 0) : null;

  return {
    buckets,
    peakHourUtc,
    total,
    synthesized: true,
  };
}
