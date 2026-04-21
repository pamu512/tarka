export {
  BehaviorCollector,
  type BehaviorSignals,
  type TypingSignals,
  type MouseSignals,
  type ScrollSignals,
  type TouchSignals,
  type SessionSignals,
  type BotIndicators,
} from "./behavior.js";

export {
  describeSdkCapabilities,
  getSdkRuntime,
  resolveCollectorTimeouts,
  withTimeoutFailOpen,
  type CollectorTimeoutsMs,
  type SdkCapabilityMatrix,
  type SdkRuntime,
} from "./runtime.js";

import type { BehaviorCollector as BehaviorCollectorClass, BehaviorSignals } from "./behavior.js";
import type { CollectorTimeoutsMs, SdkCapabilityMatrix } from "./runtime.js";
import {
  describeSdkCapabilities,
  resolveCollectorTimeouts,
  withTimeoutFailOpen,
} from "./runtime.js";

export type EventType =
  | "login"
  | "payment"
  | "signup"
  | "device"
  | "session"
  | "custom";

export type GeoSource =
  | "browser_gps"
  | "browser_ip_guess"
  | "none"
  | "unknown";

export interface DeviceSignals {
  is_emulator: boolean;
  is_vpn: boolean;
  is_spoofed_location: boolean;
  is_bot: boolean;
  is_repackaged: boolean;
  webdriver_detected: boolean;
  headless_detected: boolean;
  automation_detected: boolean;
  vpn_interface_detected: boolean;
  mock_location_detected: boolean;
  timezone_geo_mismatch: boolean;
  canvas_fp_hash: string | null;
  webgl_renderer: string | null;
  screen_res: string | null;
  touch_support: boolean | null;
  battery_api_present: boolean | null;
  language: string | null;
  platform_version: string | null;

  // CAPTCHA
  captcha?: CaptchaResult | null;

  // Extended fingerprinting
  audio_fp_hash: string | null;
  connection_type: string | null;
  device_memory: number | null;
  hardware_concurrency: number | null;
  color_depth: number | null;
  timezone: string | null;
  timezone_offset: number | null;
  do_not_track: boolean | null;
  cookie_enabled: boolean | null;
  local_storage_available: boolean | null;
  session_storage_available: boolean | null;
  indexed_db_available: boolean | null;
  max_touch_points: number | null;
  pdf_viewer_enabled: boolean | null;

  /** Optional browser GPS (opt-in via DecisionClientOptions.enableGeo). */
  geo_lat: number | null;
  geo_lon: number | null;
  geo_accuracy_m: number | null;
  geo_source: GeoSource;
  geo_ts: string | null;
}

export interface CaptchaResult {
  provider: "recaptcha_v2" | "recaptcha_v3" | "hcaptcha" | "turnstile" | "none";
  token: string | null;
  score: number | null;
  success: boolean;
  challenge_ts: string | null;
  hostname: string | null;
  error_codes: string[];
}

export interface Attestation {
  nonce: string;
  token: string;
  provider: "play_integrity" | "app_attest" | "browser_challenge";
}

export interface DeviceContext {
  device_id: string;
  platform: "web" | "android" | "ios" | "server";
  signals: DeviceSignals;
  attestation?: Attestation | null;
  behavior?: BehaviorSignals | null;
}

export interface EvaluateRequest {
  tenant_id: string;
  event_type: EventType;
  entity_id: string;
  session_id?: string | null;
  payload?: Record<string, unknown>;
  device_context?: DeviceContext | null;
  metadata?: Record<string, unknown>;
}

/** Body for `POST /v1/events` and batch items — same shape as evaluate without requiring a sync score. */
export type IngestEventRequest = EvaluateRequest;

export interface IngestEventResponse {
  accepted: boolean;
  stream_seq: number;
  ingest_id: string;
  duplicate?: boolean;
}

export interface IngestBatchResultItem {
  ingest_id: string;
  seq: number;
}

export interface IngestBatchResponse {
  accepted: number;
  results: IngestBatchResultItem[];
  duplicate?: boolean;
}

export interface EvaluateResponse {
  trace_id: string;
  decision: string;
  score: number;
  tags: string[];
  rule_hits?: string[];
  reasons?: string[];
  ml_score?: number | null;
  inference_context: InferenceContext;
  recommended_action?: string | null;
  /** When graph risk ran: tarka.graph_decision_explanation/v1 (see contracts/schemas). */
  graph_decision_explanation?: Record<string, unknown> | null;
}

/** Matches `InferenceContext` in `contracts/openapi/decision-api.yaml` (evaluate response). */
export type ConfidenceTier = "low" | "medium" | "high";

export interface MlTopFactor {
  code: string;
  description: string;
  impact: string;
}

export interface InferenceContext {
  schema_version: string;
  calibration_profile: string;
  expected_calibration_version: number;
  confidence_tier_label?: string;
  driver_explain?: Array<{ reason: string; category: string; label: string }>;
  integrity_confidence: number;
  tamper_risk: number;
  network_trust: number;
  replay_risk: number;
  geo_consistency_risk: number;
  top_signals: string[];
  confidence_tier: ConfidenceTier;
  driver_reasons: string[];
  colocation_risk: number;
  copresence_risk: number;
  impossible_travel_risk: number;
  velocity_events_5m: number;
  velocity_events_1h: number;
  velocity_events_24h: number;
  /** v1.2+ ranked factors from ml-scoring */
  ml_top_factors?: MlTopFactor[];
  ml_summary?: string | null;
  ml_model?: string | null;
}

// --------------- Device Signal Collector ---------------

async function sha256Hex(data: string): Promise<string> {
  const buf = new TextEncoder().encode(data);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function detectWebdriver(): boolean {
  if (typeof navigator === "undefined") return false;
  if ((navigator as any).webdriver === true) return true;
  if ((window as any).__nightmare) return true;
  if ((window as any).domAutomation || (window as any).domAutomationController)
    return true;
  return false;
}

function detectHeadless(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("headlesschrome") || ua.includes("phantomjs")) return true;
  if (
    navigator.plugins !== undefined &&
    navigator.plugins.length === 0 &&
    !/mobile/i.test(ua)
  )
    return true;
  if (typeof (navigator as any).languages === "undefined") return true;
  if ((navigator as any).languages?.length === 0) return true;
  return false;
}

function detectAutomation(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as any;
  if (w._phantom || w.callPhantom) return true;
  if (w.__selenium_unwrapped || w.__webdriver_evaluate) return true;
  if (w._Selenium_IDE_Recorder) return true;
  if (document.documentElement?.getAttribute("webdriver")) return true;
  return false;
}

function getCanvasFingerprint(): string | null {
  if (typeof document === "undefined") return null;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 200;
    canvas.height = 50;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = "#f60";
    ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = "#069";
    ctx.font = "14px Arial";
    ctx.fillText("Tarka fp", 2, 15);
    ctx.fillStyle = "rgba(102,204,0,0.7)";
    ctx.fillText("Tarka fp", 4, 17);
    return canvas.toDataURL();
  } catch {
    return null;
  }
}

function getWebGLRenderer(): string | null {
  if (typeof document === "undefined") return null;
  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) return null;
    const ext = (gl as WebGLRenderingContext).getExtension(
      "WEBGL_debug_renderer_info"
    );
    if (!ext) return null;
    return (gl as WebGLRenderingContext).getParameter(
      ext.UNMASKED_RENDERER_WEBGL
    );
  } catch {
    return null;
  }
}

function detectVpnWebRTC(timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof RTCPeerConnection === "undefined") {
      resolve(false);
      return;
    }
    const timer = setTimeout(() => resolve(false), Math.max(1, timeoutMs));
    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      const candidates: string[] = [];
      pc.onicecandidate = (e) => {
        if (!e.candidate) {
          clearTimeout(timer);
          pc.close();
          const hasPrivate = candidates.some(
            (c) =>
              /10\.\d+\.\d+\.\d+/.test(c) ||
              /192\.168\.\d+\.\d+/.test(c) ||
              /172\.(1[6-9]|2\d|3[01])\.\d+\.\d+/.test(c)
          );
          resolve(hasPrivate);
          return;
        }
        candidates.push(e.candidate.candidate);
      };
      pc.createDataChannel("");
      pc.createOffer().then((o) => pc.setLocalDescription(o));
    } catch {
      clearTimeout(timer);
      resolve(false);
    }
  });
}

interface SimpleBehaviorState {
  hasInteraction: boolean;
  moveCount: number;
  keyCount: number;
  destroy: () => void;
}

function createBehaviorCollector(): SimpleBehaviorState {
  const state: SimpleBehaviorState = {
    hasInteraction: false,
    moveCount: 0,
    keyCount: 0,
    destroy: () => {},
  };
  if (typeof window === "undefined") return state;
  const onMove = () => {
    state.moveCount++;
    state.hasInteraction = true;
  };
  const onKey = () => {
    state.keyCount++;
    state.hasInteraction = true;
  };
  const onTouch = () => {
    state.hasInteraction = true;
  };
  window.addEventListener("mousemove", onMove, { passive: true });
  window.addEventListener("keydown", onKey, { passive: true });
  window.addEventListener("touchstart", onTouch, { passive: true });
  state.destroy = () => {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("keydown", onKey);
    window.removeEventListener("touchstart", onTouch);
  };
  return state;
}

async function getAudioFingerprint(): Promise<string | null> {
  if (typeof AudioContext === "undefined" && typeof (window as any).webkitAudioContext === "undefined") return null;
  if (typeof crypto === "undefined" || typeof crypto.subtle === "undefined") return null;
  try {
    const AC = AudioContext || (window as any).webkitAudioContext;
    const ctx = new AC();
    const oscillator = ctx.createOscillator();
    const analyser = ctx.createAnalyser();
    const gain = ctx.createGain();
    const scriptProcessor = ctx.createScriptProcessor(4096, 1, 1);

    gain.gain.value = 0; // silent
    oscillator.type = "triangle";
    oscillator.connect(analyser);
    analyser.connect(scriptProcessor);
    scriptProcessor.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start(0);

    const fp = await new Promise<string>((resolve) => {
      scriptProcessor.onaudioprocess = (event) => {
        const data = event.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += Math.abs(data[i]);
        resolve(sum.toString());
        oscillator.stop();
        scriptProcessor.disconnect();
        gain.disconnect();
        ctx.close();
      };
    });
    return await sha256Hex(fp);
  } catch {
    return null;
  }
}

function getConnectionType(): string | null {
  if (typeof navigator === "undefined") return null;
  const conn = (navigator as any).connection || (navigator as any).mozConnection || (navigator as any).webkitConnection;
  return conn?.effectiveType || conn?.type || null;
}

function getTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return null;
  }
}

function collectBrowserGeo(
  timeoutMs: number
): Promise<{
  lat: number;
  lon: number;
  accuracy_m: number | null;
  ts: string;
} | null> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    const t = setTimeout(() => resolve(null), timeoutMs);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(t);
        resolve({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m:
            typeof pos.coords.accuracy === "number" && !Number.isNaN(pos.coords.accuracy)
              ? pos.coords.accuracy
              : null,
          ts: new Date(pos.timestamp || Date.now()).toISOString(),
        });
      },
      () => {
        clearTimeout(t);
        resolve(null);
      },
      { enableHighAccuracy: true, maximumAge: 60_000, timeout: timeoutMs }
    );
  });
}

function isStorageAvailable(type: "localStorage" | "sessionStorage" | "indexedDB"): boolean | null {
  try {
    if (typeof window === "undefined") return null;
    if (type === "indexedDB") return typeof indexedDB !== "undefined";
    const storage = window[type];
    const key = "__tarka_test__";
    storage.setItem(key, "1");
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export interface DeviceSignalCollectorOptions {
  enableGeo?: boolean;
  /** Override per-source timeouts (ms); zero skips that async collector (fail-open). */
  collectorTimeouts?: Partial<CollectorTimeoutsMs>;
  /** Pre-computed capabilities; default `describeSdkCapabilities()`. */
  capabilities?: SdkCapabilityMatrix;
  /** Log `console.warn` when a collector hits its timeout (browser only). */
  failOpenLogTimeouts?: boolean;
}

export class DeviceSignalCollector {
  private behavior: SimpleBehaviorState;
  private canvasRaw: string | null = null;
  private behaviorCollector: BehaviorCollectorClass | null = null;
  private readonly enableGeo: boolean;
  private readonly caps: SdkCapabilityMatrix;
  private readonly timeouts: CollectorTimeoutsMs;
  private readonly failOpenLogTimeouts: boolean;

  constructor(
    behaviorCollector?: BehaviorCollectorClass,
    opts?: DeviceSignalCollectorOptions,
  ) {
    this.behavior = createBehaviorCollector();
    this.canvasRaw = getCanvasFingerprint();
    this.behaviorCollector = behaviorCollector ?? null;
    this.enableGeo = opts?.enableGeo === true;
    this.caps = opts?.capabilities ?? describeSdkCapabilities();
    this.timeouts = resolveCollectorTimeouts(this.caps, opts?.collectorTimeouts);
    this.failOpenLogTimeouts = opts?.failOpenLogTimeouts === true;
  }

  /** Capability matrix for this environment (browser vs server, APIs present). */
  getCapabilities(): SdkCapabilityMatrix {
    return this.caps;
  }

  async collect(): Promise<DeviceSignals> {
    const webdriver = detectWebdriver();
    const headless = detectHeadless();
    const automation = detectAutomation();
    const vpn =
      this.timeouts.vpn > 0 && this.caps.has_rtc_peer_connection
        ? await withTimeoutFailOpen(
            detectVpnWebRTC(this.timeouts.vpn),
            this.timeouts.vpn,
            false,
            { collectorName: "vpn_webrtc", logTimeouts: this.failOpenLogTimeouts },
          )
        : false;
    const webglRenderer = getWebGLRenderer();
    const canvasHash = this.canvasRaw
      ? await sha256Hex(this.canvasRaw)
      : null;

    const isBot =
      !this.behavior.hasInteraction &&
      this.behavior.moveCount === 0 &&
      this.behavior.keyCount === 0;

    const screen_res =
      typeof screen !== "undefined"
        ? `${screen.width}x${screen.height}`
        : null;
    const touch =
      typeof navigator !== "undefined"
        ? "ontouchstart" in window || navigator.maxTouchPoints > 0
        : null;
    const battery =
      typeof navigator !== "undefined" && "getBattery" in navigator;
    const lang =
      typeof navigator !== "undefined" ? navigator.language || null : null;
    const pv =
      typeof navigator !== "undefined" ? navigator.userAgent || null : null;

    let geo_lat: number | null = null;
    let geo_lon: number | null = null;
    let geo_accuracy_m: number | null = null;
    let geo_source: GeoSource = "none";
    let geo_ts: string | null = null;
    if (this.enableGeo && this.timeouts.geo > 0 && this.caps.has_geolocation) {
      const g = await collectBrowserGeo(this.timeouts.geo);
      if (g) {
        geo_lat = g.lat;
        geo_lon = g.lon;
        geo_accuracy_m = g.accuracy_m;
        geo_source = "browser_gps";
        geo_ts = g.ts;
      } else {
        geo_source = "unknown";
      }
    }

    return {
      is_emulator: headless && webdriver,
      is_vpn: vpn,
      is_spoofed_location: false,
      is_bot: isBot,
      is_repackaged: false,
      webdriver_detected: webdriver,
      headless_detected: headless,
      automation_detected: automation,
      vpn_interface_detected: vpn,
      mock_location_detected: false,
      timezone_geo_mismatch: false,
      canvas_fp_hash: canvasHash,
      webgl_renderer: webglRenderer,
      screen_res,
      touch_support: touch,
      battery_api_present: battery,
      language: lang,
      platform_version: pv,
      audio_fp_hash:
        this.timeouts.audio > 0 && this.caps.has_audio_context && this.caps.has_subtle_crypto
          ? await withTimeoutFailOpen(
              getAudioFingerprint(),
              this.timeouts.audio,
              null,
              { collectorName: "audio_fp", logTimeouts: this.failOpenLogTimeouts },
            )
          : null,
      connection_type: getConnectionType(),
      device_memory: typeof navigator !== "undefined" ? (navigator as any).deviceMemory ?? null : null,
      hardware_concurrency: typeof navigator !== "undefined" ? navigator.hardwareConcurrency ?? null : null,
      color_depth: typeof screen !== "undefined" ? screen.colorDepth : null,
      timezone: getTimezone(),
      timezone_offset: new Date().getTimezoneOffset(),
      do_not_track: typeof navigator !== "undefined" ? navigator.doNotTrack === "1" : null,
      cookie_enabled: typeof navigator !== "undefined" ? navigator.cookieEnabled : null,
      local_storage_available: isStorageAvailable("localStorage"),
      session_storage_available: isStorageAvailable("sessionStorage"),
      indexed_db_available: isStorageAvailable("indexedDB"),
      max_touch_points: typeof navigator !== "undefined" ? navigator.maxTouchPoints ?? null : null,
      pdf_viewer_enabled: typeof navigator !== "undefined" ? (navigator as any).pdfViewerEnabled ?? null : null,
      captcha: null,
      geo_lat,
      geo_lon,
      geo_accuracy_m,
      geo_source,
      geo_ts,
    };
  }

  async buildDeviceContext(): Promise<DeviceContext> {
    const signals = await this.collect();
    const components = [
      signals.canvas_fp_hash || "",
      signals.webgl_renderer || "",
      signals.audio_fp_hash || "",
      signals.screen_res || "",
      signals.language || "",
      String(signals.hardware_concurrency || ""),
      String(signals.timezone_offset ?? ""),
    ].join("|");
    const device_id = await sha256Hex(components);

    return {
      device_id,
      platform: "web",
      signals,
      attestation: null,
      behavior: this.behaviorCollector?.getSignals() ?? null,
    };
  }

  destroy(): void {
    this.behavior.destroy();
    this.behaviorCollector?.destroy();
  }
}

// --------------- Attestation ---------------

async function hmacSign(key: string, message: string): Promise<string> {
  const enc = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    enc.encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, enc.encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// --------------- Decision Client ---------------

export interface DecisionClientOptions {
  baseUrl: string;
  apiKey?: string;
  timeoutMs?: number;
  autoCollectSignals?: boolean;
  /** When true, attempts a one-shot browser geolocation read (non-blocking timeout). Off by default. */
  enableGeo?: boolean;
  /** Per-signal-collector timeouts (VPN WebRTC, audio FP, geo); fail-open on timeout. */
  collectorTimeouts?: Partial<CollectorTimeoutsMs>;
  /** Log when a collector times out (browser only). */
  failOpenLogTimeouts?: boolean;
  /** Override environment detection (tests). */
  capabilities?: SdkCapabilityMatrix;
}

export class DecisionClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private collector: DeviceSignalCollector | null;

  constructor(opts: DecisionClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey || "";
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    this.collector =
      opts.autoCollectSignals !== false
        ? new DeviceSignalCollector(undefined, {
            enableGeo: opts.enableGeo,
            collectorTimeouts: opts.collectorTimeouts,
            failOpenLogTimeouts: opts.failOpenLogTimeouts,
            capabilities: opts.capabilities,
          })
        : null;
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) h["X-API-Key"] = this.apiKey;
    return h;
  }

  private async fetchWithTimeout(
    url: string,
    init: RequestInit
  ): Promise<Response> {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const r = await fetch(url, { ...init, signal: ctrl.signal });
      if (!r.ok) throw new Error(await r.text());
      return r;
    } finally {
      clearTimeout(t);
    }
  }

  async requestChallenge(tenantId: string): Promise<string> {
    const r = await this.fetchWithTimeout(
      this.url("/v1/attestation/challenge"),
      {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({ tenant_id: tenantId }),
      }
    );
    const data = (await r.json()) as { nonce: string };
    return data.nonce;
  }

  async evaluate(body: EvaluateRequest): Promise<EvaluateResponse> {
    if (this.collector && !body.device_context) {
      const ctx = await this.collector.buildDeviceContext();

      // browser challenge attestation
      try {
        const nonce = await this.requestChallenge(body.tenant_id);
        const token = await hmacSign(
          ctx.device_id,
          nonce + ctx.device_id
        );
        ctx.attestation = { nonce, token, provider: "browser_challenge" };
      } catch {
        // attestation is best-effort
      }

      body = { ...body, device_context: ctx };
    }

    const r = await this.fetchWithTimeout(
      this.url("/v1/decisions/evaluate"),
      {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify(body),
      }
    );
    return (await r.json()) as EvaluateResponse;
  }

  async verifyCaptcha(
    provider: "recaptcha_v2" | "recaptcha_v3" | "hcaptcha" | "turnstile",
    token: string,
    siteKey?: string,
  ): Promise<CaptchaResult> {
    try {
      const r = await this.fetchWithTimeout(
        this.url("/v1/captcha/verify"),
        {
          method: "POST",
          headers: this.headers(),
          body: JSON.stringify({ provider, token, site_key: siteKey }),
        },
      );
      return (await r.json()) as CaptchaResult;
    } catch {
      return {
        provider,
        token: null,
        score: null,
        success: false,
        challenge_ts: null,
        hostname: null,
        error_codes: ["verification_failed"],
      };
    }
  }

  async evaluateWithCaptcha(
    body: EvaluateRequest,
    captchaProvider: "recaptcha_v2" | "recaptcha_v3" | "hcaptcha" | "turnstile",
    captchaToken: string,
  ): Promise<EvaluateResponse> {
    const captchaResult = await this.verifyCaptcha(captchaProvider, captchaToken);

    if (this.collector && !body.device_context) {
      const ctx = await this.collector.buildDeviceContext();
      ctx.signals.captcha = captchaResult;
      body = { ...body, device_context: ctx };
    } else if (body.device_context) {
      body.device_context.signals.captcha = captchaResult;
    }

    return this.evaluate(body);
  }

  async getAudit(traceId: string, tenantId: string): Promise<Record<string, unknown>> {
    const q = new URLSearchParams({ tenant_id: tenantId });
    const r = await this.fetchWithTimeout(
      this.url(`/v1/audit/${traceId}?${q}`),
      { headers: this.headers() }
    );
    return (await r.json()) as Record<string, unknown>;
  }

  destroy(): void {
    this.collector?.destroy();
  }
}

// --------------- Event Ingest Client (async NATS path) ---------------

export interface EventIngestClientOptions {
  /** Base URL of the event-ingest service (e.g. http://localhost:8001). */
  baseUrl: string;
  apiKey?: string;
  timeoutMs?: number;
}

export class EventIngestClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;

  constructor(opts: EventIngestClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey || "";
    this.timeoutMs = opts.timeoutMs ?? 10_000;
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) h["X-API-Key"] = this.apiKey;
    return h;
  }

  private async fetchWithTimeout(
    url: string,
    init: RequestInit
  ): Promise<Response> {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const r = await fetch(url, { ...init, signal: ctrl.signal });
      if (!r.ok) throw new Error(await r.text());
      return r;
    } finally {
      clearTimeout(t);
    }
  }

  async sendEvent(
    body: IngestEventRequest,
    idempotencyKey?: string
  ): Promise<IngestEventResponse> {
    const h = this.headers();
    if (idempotencyKey) h["Idempotency-Key"] = idempotencyKey;
    const r = await this.fetchWithTimeout(this.url("/v1/events"), {
      method: "POST",
      headers: h,
      body: JSON.stringify({
        tenant_id: body.tenant_id,
        event_type: body.event_type,
        entity_id: body.entity_id,
        session_id: body.session_id ?? undefined,
        payload: body.payload ?? {},
        device_context: body.device_context ?? undefined,
        metadata: body.metadata ?? undefined,
      }),
    });
    return (await r.json()) as IngestEventResponse;
  }

  async sendBatch(
    events: IngestEventRequest[],
    idempotencyKey?: string
  ): Promise<IngestBatchResponse> {
    const h = this.headers();
    if (idempotencyKey) h["Idempotency-Key"] = idempotencyKey;
    const r = await this.fetchWithTimeout(this.url("/v1/events/batch"), {
      method: "POST",
      headers: h,
      body: JSON.stringify({ events }),
    });
    return (await r.json()) as IngestBatchResponse;
  }
}
