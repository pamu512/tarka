import type { HardwareSignalMap } from "./hardwareSignals";
import type { DecisionSurface, TransactionRow } from "./transactionRow";

const STATUSES: readonly DecisionSurface[] = ["Block", "Allow", "Challenge"];

const CHANNELS = ["ach", "card", "wire", "rtp", "crypto", "wallet"] as const;

/**
 * Adjacent rows `(2k, 2k+1)` share a cluster; odd row flips two keys so similarity vs even row is ~80%
 * (8/10 hardware signals match) for visual diff demos.
 */
function seedHardwareSignals(rowIndex: number): HardwareSignalMap {
  const cluster = Math.floor(rowIndex / 2);
  const base: HardwareSignalMap = {
    canvas_fingerprint: `sha256:${(cluster * 1103515245).toString(16).slice(0, 24)}`,
    webgl_vendor: "Google Inc. (ANGLE)",
    webgl_renderer: "ANGLE (Intel Iris OpenGL)",
    audio_context_hash: `ac_${cluster}`,
    screen_resolution: "2560×1440",
    color_depth: "24",
    timezone: "America/New_York",
    platform: "Win32",
    hardware_concurrency: "12",
    touch_points: "0",
    device_memory_gb: "8",
  };
  if (rowIndex % 2 === 1) {
    return {
      ...base,
      canvas_fingerprint: "sha256:ALT_COLLISION_CLUSTER_B",
      webgl_vendor: "ANGLE_DIFF_VENDOR_X",
    };
  }
  return base;
}

/** Monotonic ISO timestamps descending by row index (newest first when rendered top-down). */
export function buildTransactionSeed(count: number, nowMs: number = Date.now()): TransactionRow[] {
  const rows: TransactionRow[] = new Array(count);
  for (let i = 0; i < count; i++) {
    const ts = new Date(nowMs - i * 750).toISOString();
    rows[i] = {
      id: `tx-${i}`,
      timestamp: ts,
      traceId: `tr-${(i * 7919) % 900_000}`,
      entityId: `ent-${(i * 104729) % 250_000}`,
      amountCents: ((i * 9973) % 500_000) + 1,
      currency: "USD",
      status: STATUSES[i % 3]!,
      channel: CHANNELS[i % CHANNELS.length]!,
      hardwareSignals: seedHardwareSignals(i),
    };
  }
  return rows;
}
