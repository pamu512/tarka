/** Day-1 AGE Hunt bound. Raise only when a later slice documents an AGE-safe fixed k. */
export const AGE_HUNT_DEPTH_MAX = 1;
export const HUNT_DEPTH_SCHEMA_ID = "tarka.hunt_depth/v1";
export const DEPTH_NOT_YET_REPORTED = "depth not yet reported";
export const HUNT_DEPTH_CAPPED = "hunt:depth_capped";

export type HuntDepthFields = {
  schema_id?: string;
  hunt_depth_max?: number;
  depth_requested?: number;
  depth_applied?: number | null;
  degrade_reason?: string | null;
};

export type HuntDepthHonesty = {
  planeOff: boolean;
  depth_requested: number;
  depth_applied: number | null;
  hunt_depth_max: number;
  degrade_reason: string | null;
  appliedLabel: string;
  degraded: boolean;
  banner: string;
};

export function graphServiceUrlOn(raw: string | undefined | null): boolean {
  return Boolean(raw?.trim());
}

function readInt(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  return undefined;
}

/** Wire tip fields when present. Missing fields stay null — never invent hop counts. */
export function readHuntDepthFromPayload(payload: unknown): HuntDepthFields | null {
  if (!payload || typeof payload !== "object") return null;
  const rec = payload as Record<string, unknown>;
  const hasSchema = rec.schema_id === HUNT_DEPTH_SCHEMA_ID;
  const hasField =
    "depth_applied" in rec ||
    "depth_requested" in rec ||
    "degrade_reason" in rec ||
    "hunt_depth_max" in rec;
  if (!hasSchema && !hasField) return null;
  const appliedRaw = rec.depth_applied;
  const applied = readInt(appliedRaw);
  return {
    schema_id: typeof rec.schema_id === "string" ? rec.schema_id : undefined,
    hunt_depth_max: readInt(rec.hunt_depth_max),
    depth_requested: readInt(rec.depth_requested),
    depth_applied: applied ?? null,
    degrade_reason: typeof rec.degrade_reason === "string" && rec.degrade_reason.trim()
      ? rec.degrade_reason.trim()
      : rec.degrade_reason === null
        ? null
        : undefined,
  };
}

export function resolveHuntDepthHonesty(opts: {
  graphServiceUrl?: string | null;
  depthRequested: number;
  api?: HuntDepthFields | null;
}): HuntDepthHonesty {
  const requestedHint = Number.isFinite(opts.depthRequested)
    ? Math.trunc(opts.depthRequested)
    : AGE_HUNT_DEPTH_MAX;
  if (!graphServiceUrlOn(opts.graphServiceUrl)) {
    return {
      planeOff: true,
      depth_requested: requestedHint,
      depth_applied: null,
      hunt_depth_max: AGE_HUNT_DEPTH_MAX,
      degrade_reason: null,
      appliedLabel: DEPTH_NOT_YET_REPORTED,
      degraded: false,
      banner:
        "GRAPH_SERVICE_URL is empty. Hunt and sibling-identity hops are off. Evaluate still runs. Empty URL does not invent neighbors. This is not an outage.",
    };
  }

  const max = opts.api?.hunt_depth_max ?? AGE_HUNT_DEPTH_MAX;
  const requested = opts.api?.depth_requested ?? requestedHint;
  const applied =
    typeof opts.api?.depth_applied === "number" && Number.isFinite(opts.api.depth_applied)
      ? opts.api.depth_applied
      : null;
  const appliedLabel = applied == null ? DEPTH_NOT_YET_REPORTED : String(applied);
  const overMax = requested > max;
  const overApplied = applied != null && requested > applied;
  const apiReason = opts.api?.degrade_reason?.trim() || null;
  const degrade_reason = apiReason ?? (overMax || overApplied ? HUNT_DEPTH_CAPPED : null);
  const degraded = Boolean(degrade_reason);
  const banner = degraded
    ? `Hunt depth requested ${requested}, applied ${appliedLabel} (AGE-safe max ${max}). ${degrade_reason}.`
    : `Hunt depth requested ${requested}, applied ${appliedLabel}. AGE-safe max ${max}.`;
  return {
    planeOff: false,
    depth_requested: requested,
    depth_applied: applied,
    hunt_depth_max: max,
    degrade_reason,
    appliedLabel,
    degraded,
    banner,
  };
}
