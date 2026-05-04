/**
 * Client-side behavioral entropy + passive evasion signals (native only, no third-party FP libs).
 * Heavy aggregation is offloaded to requestAnimationFrame and optionally a tiny Web Worker.
 */

const MOUSE_WORKER_SOURCE = `self.onmessage=function(e){var pts=e.data&&e.data.points;if(!Array.isArray(pts)||pts.length<2){self.postMessage({dist:0,dt:0,n:pts?pts.length:0});return;}var dist=0,i;for(i=1;i<pts.length;i++){var a=pts[i-1],b=pts[i];dist+=Math.hypot(b.x-a.x,b.y-a.y);}var dt=Math.max(1,pts[pts.length-1].t-pts[0].t);self.postMessage({dist:dist,dt:dt,n:pts.length});};`;

export interface WebRtcEntropyResult {
  /** True if any host ICE candidate looks like a private IPv4 address. */
  private_candidate_seen: boolean;
  /** SHA-256 hex of joined candidate strings (no raw IPs shipped). */
  candidate_digest_hex: string | null;
}

export interface CanvasEntropyResult {
  /** SHA-256 hex of rasterized canvas data URL (or OffscreenCanvas export). */
  raster_digest_hex: string | null;
}

export interface HardwareEntropySnapshot {
  hardware_concurrency: number | null;
  device_memory_gb: number | null;
}

function median(nums: number[]): number {
  if (nums.length === 0) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

/** Base64url (no padding) for UTF-8 JSON payloads. */
export function b64urlEncodeUtf8(json: string): string {
  const bytes = new TextEncoder().encode(json);
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  if (typeof btoa === "undefined") {
    throw new Error("btoa is required for telemetry encoding in this environment");
  }
  const b64 = btoa(bin);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function sha256HexUtf8(data: string): Promise<string> {
  const buf = new TextEncoder().encode(data);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256HexBytes(data: Uint8Array): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", data.buffer as ArrayBuffer);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Gather WebRTC ICE candidates; hash candidates; flag private IPv4 leaks (passive signal). */
export function gatherWebRtcEntropy(timeoutMs: number): Promise<WebRtcEntropyResult> {
  return new Promise((resolve) => {
    if (typeof RTCPeerConnection === "undefined") {
      resolve({ private_candidate_seen: false, candidate_digest_hex: null });
      return;
    }
    const timer = setTimeout(() => finish([]), Math.max(50, timeoutMs));
    const lines: string[] = [];

    function finish(cands: string[]) {
      clearTimeout(timer);
      const joined = cands.join("\n");
      const digestTask =
        joined.length > 0
          ? sha256HexUtf8(joined).then((h) => h)
          : Promise.resolve(null as string | null);
      digestTask.then((candidate_digest_hex) => {
        const private_candidate_seen = cands.some(
          (c) =>
            / typ host /.test(c) &&
            (/ 10\.\d+\.\d+\.\d+ /.test(c) ||
              / 192\.168\.\d+\.\d+ /.test(c) ||
              / 172\.(1[6-9]|2\d|3[01])\.\d+\.\d+ /.test(c)),
        );
        resolve({ private_candidate_seen, candidate_digest_hex });
      });
    }

    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      pc.onicecandidate = (e) => {
        if (e.candidate?.candidate) lines.push(e.candidate.candidate);
        if (!e.candidate) {
          pc.close();
          finish(lines);
        }
      };
      pc.createDataChannel("");
      pc.createOffer().then((o) => pc.setLocalDescription(o)).catch(() => finish(lines));
    } catch {
      clearTimeout(timer);
      resolve({ private_candidate_seen: false, candidate_digest_hex: null });
    }
  });
}

/** Raster canvas fingerprint; prefer idle time to avoid blocking first paint. */
export function rasterCanvasDigest(
  draw: (ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D) => void,
  width = 200,
  height = 50,
): Promise<string | null> {
  const run = (): Promise<string | null> =>
    new Promise((resolve) => {
      try {
        if (typeof OffscreenCanvas !== "undefined") {
          const c = new OffscreenCanvas(width, height);
          const ctx = c.getContext("2d");
          if (!ctx) {
            resolve(null);
            return;
          }
          draw(ctx);
          c.convertToBlob({ type: "image/png" })
            .then((blob) => blob.arrayBuffer())
            .then((ab) => sha256HexBytes(new Uint8Array(ab)))
            .then(resolve)
            .catch(() => resolve(null));
          return;
        }
        if (typeof document === "undefined") {
          resolve(null);
          return;
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          resolve(null);
          return;
        }
        draw(ctx);
        const url = canvas.toDataURL("image/png");
        void sha256HexUtf8(url).then(resolve);
      } catch {
        resolve(null);
      }
    });

  if (typeof requestIdleCallback !== "undefined") {
    return new Promise((resolve) => {
      requestIdleCallback(() => void run().then(resolve), { timeout: 2000 });
    });
  }
  return run();
}

export function defaultCanvasDraw(
  ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D,
): void {
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#f60";
  ctx.fillRect(125, 1, 62, 20);
  ctx.fillStyle = "#069";
  ctx.font = "14px Arial";
  ctx.fillText("Tarka entropy", 2, 15);
  ctx.fillStyle = "rgba(102,204,0,0.7)";
  ctx.fillText("Tarka entropy", 4, 17);
}

export function readHardwareEntropy(): HardwareEntropySnapshot {
  if (typeof navigator === "undefined") {
    return { hardware_concurrency: null, device_memory_gb: null };
  }
  const dm = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  return {
    hardware_concurrency: typeof navigator.hardwareConcurrency === "number" ? navigator.hardwareConcurrency : null,
    device_memory_gb: typeof dm === "number" ? dm : null,
  };
}

export interface MouseWorkerAgg {
  dist: number;
  dt: number;
  n: number;
}

export function createMouseDistanceWorker(): Worker | null {
  if (typeof Worker === "undefined" || typeof Blob === "undefined" || typeof URL === "undefined") {
    return null;
  }
  try {
    const blob = new Blob([MOUSE_WORKER_SOURCE], { type: "text/javascript;charset=utf-8" });
    return new Worker(URL.createObjectURL(blob));
  } catch {
    return null;
  }
}

export function aggregateMousePointsLocal(
  points: ReadonlyArray<{ t: number; x: number; y: number }>,
): MouseWorkerAgg {
  if (points.length < 2) return { dist: 0, dt: 0, n: points.length };
  let dist = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!;
    const b = points[i]!;
    dist += Math.hypot(b.x - a.x, b.y - a.y);
  }
  const dt = Math.max(1, points[points.length - 1]!.t - points[0]!.t);
  return { dist, dt, n: points.length };
}

export function typingHesitationCount(interKeyMs: ReadonlyArray<number>, thresholdMs = 500): number {
  let n = 0;
  for (const v of interKeyMs) {
    if (v >= thresholdMs) n++;
  }
  return n;
}

export { median };

/** Sealed telemetry: base64url(JSON) + integrity digest (TLS provides confidentiality). */
export async function buildTelemetrySealedPacket(payload: Record<string, unknown>): Promise<{
  v: 1;
  enc: string;
  int: string;
}> {
  const json = JSON.stringify(payload);
  const enc = b64urlEncodeUtf8(json);
  const int = await sha256HexUtf8(enc);
  return { v: 1, enc, int };
}

export async function verifyTelemetryInt(enc: string, int: string): Promise<boolean> {
  const h = await sha256HexUtf8(enc);
  return h === int;
}
