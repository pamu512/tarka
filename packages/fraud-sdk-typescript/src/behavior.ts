import {
  aggregateMousePointsLocal,
  createMouseDistanceWorker,
  median,
  typingHesitationCount,
  type MouseWorkerAgg,
} from "./telemetry.js";

export interface TypingSignals {
  avg_inter_key_ms: number;
  std_inter_key_ms: number;
  median_inter_key_ms: number;
  avg_hold_ms: number;
  key_count: number;
  /** Count of inter-key gaps ≥ 500ms (human hesitation). */
  hesitation_events_gt_500ms: number;
}

export interface MouseSignals {
  avg_speed_px_ms: number;
  std_speed_px_ms: number;
  click_count: number;
  avg_click_interval_ms: number;
  /** Estimated pointer samples per second from recent movement cadence. */
  samples_per_second_est: number;
  /** Std-dev of recent pointer step lengths (px); near-zero with activity suggests synthetic / headless input. */
  path_jitter_px: number;
  /** Path length accumulated over the sampling window (px). */
  path_length_px: number;
}

export interface ScrollSignals {
  total_scrolls: number;
  direction_changes: number;
  avg_speed: number;
}

export interface TouchSignals {
  avg_force: number;
  touch_count: number;
  /** Distinct touch-drag strokes (touchmove sequences). */
  touchstroke_count: number;
  /** Approximate length of recent touch curves (px). */
  curve_length_px: number;
  /** Variance of instantaneous touch speed between samples (px²/ms² scale). */
  curve_speed_variance: number;
}

export interface SessionSignals {
  time_to_first_interaction_ms: number;
  total_active_ms: number;
  idle_count: number;
  paste_count: number;
  tab_switches: number;
}

export interface BotIndicators {
  zero_mouse_movement: boolean;
  constant_typing_speed: boolean;
  no_scroll: boolean;
  suspiciously_fast: boolean;
}

export interface BehaviorSignals {
  typing: TypingSignals;
  mouse: MouseSignals;
  scroll: ScrollSignals;
  touch: TouchSignals;
  session: SessionSignals;
  bot_indicators: BotIndicators;
}

function mean(arr: number[]): number {
  if (arr.length === 0) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function stddev(arr: number[]): number {
  if (arr.length < 2) return 0;
  const m = mean(arr);
  const variance = arr.reduce((sum, v) => sum + (v - m) ** 2, 0) / arr.length;
  return Math.sqrt(variance);
}

export class BehaviorCollector {
  private interKeyIntervals: number[] = [];
  private keyHoldDurations: number[] = [];
  private mouseSpeeds: number[] = [];
  private stepLengthsPx: number[] = [];
  private clickTimestamps: number[] = [];
  private scrollSpeeds: number[] = [];
  private scrollDirectionChanges = 0;
  private totalScrolls = 0;
  private lastScrollDirection: "up" | "down" | null = null;
  private touchForces: number[] = [];
  private touchCount = 0;
  private pasteCount = 0;
  private tabSwitches = 0;

  private startTime: number;
  private firstInteractionTime: number | null = null;
  private lastActivityTime: number;
  private totalActiveMs = 0;
  private idleCount = 0;
  private idleTimer: ReturnType<typeof setInterval> | null = null;

  private lastKeydownTime: number | null = null;
  private keyDownTimes = new Map<string, number>();

  private pendingMouse: Array<{ t: number; x: number; y: number }> = [];
  private rafScheduled = false;
  private rafId: number | null = null;
  private mouseWorker: Worker | null = null;
  private workerPending = 0;
  private mousePathDistAcc = 0;
  private mousePathDtAcc = 0;

  private touchTracing = false;
  private touchTrace: Array<{ t: number; x: number; y: number }> = [];
  private touchstrokes = 0;

  private listeners: Array<{
    target: EventTarget;
    type: string;
    handler: EventListener;
  }> = [];

  constructor() {
    this.startTime = Date.now();
    this.lastActivityTime = this.startTime;

    if (typeof document === "undefined" || typeof window === "undefined") return;

    this.mouseWorker = createMouseDistanceWorker();
    if (this.mouseWorker) {
      this.mouseWorker.onmessage = (ev: MessageEvent<MouseWorkerAgg>) => {
        this.workerPending = Math.max(0, this.workerPending - 1);
        const d = ev.data;
        if (d && d.dt > 0 && d.n > 1) {
          this.mousePathDistAcc += d.dist;
          this.mousePathDtAcc += d.dt;
        }
      };
    }

    this.addListener(document, "keydown", this.onKeydown);
    this.addListener(document, "keyup", this.onKeyup);
    this.addListener(document, "mousemove", this.onMousemove);
    this.addListener(document, "click", this.onClick);
    this.addListener(document, "scroll", this.onScroll, true);
    this.addListener(document, "touchstart", this.onTouchstart);
    this.addListener(document, "touchmove", this.onTouchmove, { passive: true } as AddEventListenerOptions);
    this.addListener(document, "touchend", this.onTouchend);
    this.addListener(document, "paste", this.onPaste);
    this.addListener(document, "visibilitychange", this.onVisibilitychange);

    this.idleTimer = setInterval(() => this.checkIdle(), 1000);
  }

  private addListener(
    target: EventTarget,
    type: string,
    handler: (e: Event) => void,
    captureOrOptions?: boolean | AddEventListenerOptions,
  ): void {
    const bound = handler.bind(this) as EventListener;
    const opts =
      typeof captureOrOptions === "boolean"
        ? { passive: true, capture: captureOrOptions }
        : { passive: true, capture: false, ...(captureOrOptions ?? {}) };
    target.addEventListener(type, bound, opts);
    this.listeners.push({ target, type, handler: bound });
  }

  private recordActivity(): void {
    const now = Date.now();
    if (this.firstInteractionTime === null) {
      this.firstInteractionTime = now;
    }
    const gap = now - this.lastActivityTime;
    if (gap < 3000) {
      this.totalActiveMs += gap;
    }
    this.lastActivityTime = now;
  }

  private checkIdle(): void {
    if (Date.now() - this.lastActivityTime >= 3000) {
      this.idleCount++;
    }
  }

  private scheduleRafFlush(): void {
    if (this.rafScheduled) return;
    this.rafScheduled = true;
    const tick = () => {
      this.rafScheduled = false;
      this.flushFrame();
    };
    if (typeof requestAnimationFrame !== "undefined") {
      this.rafId = requestAnimationFrame(tick);
    } else {
      this.rafId = window.setTimeout(tick, 16) as unknown as number;
    }
  }

  private flushFrame(): void {
    this.rafId = null;
    const batch = this.pendingMouse.splice(0, this.pendingMouse.length);
    if (batch.length >= 2) {
      for (let i = 1; i < batch.length; i++) {
        const a = batch[i - 1]!;
        const b = batch[i]!;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy);
        const dt = Math.max(1, b.t - a.t);
        this.stepLengthsPx.push(len);
        if (this.stepLengthsPx.length > 120) this.stepLengthsPx.shift();
        const speed = len / dt;
        this.mouseSpeeds.push(speed);
        if (this.mouseSpeeds.length > 100) this.mouseSpeeds.shift();
      }
      if (this.mouseWorker && batch.length >= 2) {
        this.workerPending++;
        this.mouseWorker.postMessage({ points: batch });
      } else {
        const agg = aggregateMousePointsLocal(batch);
        if (agg.dt > 0 && agg.n > 1) {
          this.mousePathDistAcc += agg.dist;
          this.mousePathDtAcc += agg.dt;
        }
      }
    }

    if (this.touchTrace.length >= 2) {
      let len = 0;
      const speeds: number[] = [];
      for (let i = 1; i < this.touchTrace.length; i++) {
        const a = this.touchTrace[i - 1]!;
        const b = this.touchTrace[i]!;
        const seg = Math.hypot(b.x - a.x, b.y - a.y);
        len += seg;
        const dt = Math.max(1, b.t - a.t);
        speeds.push(seg / dt);
      }
      this._lastTouchCurveLen = len;
      this._lastTouchSpeedVar = speeds.length > 1 ? stddev(speeds) : 0;
      this.touchTrace.length = 0;
    }
  }

  private _lastTouchCurveLen = 0;
  private _lastTouchSpeedVar = 0;

  private onKeydown(e: Event): void {
    this.recordActivity();
    const ke = e as KeyboardEvent;
    const now = Date.now();

    if (this.lastKeydownTime !== null) {
      const interval = now - this.lastKeydownTime;
      this.interKeyIntervals.push(interval);
      if (this.interKeyIntervals.length > 80) {
        this.interKeyIntervals.shift();
      }
    }
    this.lastKeydownTime = now;

    if (!this.keyDownTimes.has(ke.code)) {
      this.keyDownTimes.set(ke.code, now);
    }
  }

  private onKeyup(e: Event): void {
    const ke = e as KeyboardEvent;
    const downTime = this.keyDownTimes.get(ke.code);
    if (downTime !== undefined) {
      const hold = Date.now() - downTime;
      this.keyHoldDurations.push(hold);
      if (this.keyHoldDurations.length > 50) {
        this.keyHoldDurations.shift();
      }
      this.keyDownTimes.delete(ke.code);
    }
  }

  private onMousemove(e: Event): void {
    this.recordActivity();
    const me = e as MouseEvent;
    this.pendingMouse.push({ t: Date.now(), x: me.clientX, y: me.clientY });
    if (this.pendingMouse.length > 256) this.pendingMouse.shift();
    this.scheduleRafFlush();
  }

  private onClick(): void {
    this.recordActivity();
    const now = Date.now();
    this.clickTimestamps.push(now);
  }

  private onScroll(e: Event): void {
    this.recordActivity();
    this.totalScrolls++;

    const target = e.target as Element | null;
    const scrollTop =
      target === document.documentElement || target === document.body
        ? window.scrollY
        : target?.scrollTop ?? 0;

    const direction: "up" | "down" =
      this.lastScrollDirection === null ? "down" : scrollTop >= 0 ? "down" : "up";

    if (this.lastScrollDirection !== null && direction !== this.lastScrollDirection) {
      this.scrollDirectionChanges++;
    }
    this.lastScrollDirection = direction;

    this.scrollSpeeds.push(Math.abs(scrollTop));
  }

  private onTouchstart(e: Event): void {
    this.recordActivity();
    this.touchCount++;
    this.touchTracing = true;
    const te = e as TouchEvent;
    if (te.touches && te.touches.length > 0) {
      const touch = te.touches[0]!;
      this.touchTrace.push({ t: Date.now(), x: touch.clientX, y: touch.clientY });
      const force = (touch as Touch & { force?: number }).force;
      if (typeof force === "number" && force > 0) {
        this.touchForces.push(force);
        if (this.touchForces.length > 20) {
          this.touchForces.shift();
        }
      }
    }
    this.touchstrokes++;
    this.scheduleRafFlush();
  }

  private onTouchmove(e: Event): void {
    if (!this.touchTracing) return;
    const te = e as TouchEvent;
    if (!te.touches?.length) return;
    const touch = te.touches[0]!;
    this.touchTrace.push({ t: Date.now(), x: touch.clientX, y: touch.clientY });
    if (this.touchTrace.length > 200) this.touchTrace.shift();
    this.scheduleRafFlush();
  }

  private onTouchend(): void {
    this.recordActivity();
    this.touchTracing = false;
    this.scheduleRafFlush();
  }

  private onPaste(): void {
    this.recordActivity();
    this.pasteCount++;
  }

  private onVisibilitychange(): void {
    if (document.hidden) {
      this.tabSwitches++;
    }
  }

  getSignals(): BehaviorSignals {
    const now = Date.now();
    const sessionDurationMs = now - this.startTime;

    const clickIntervals: number[] = [];
    for (let i = 1; i < this.clickTimestamps.length; i++) {
      clickIntervals.push(this.clickTimestamps[i]! - this.clickTimestamps[i - 1]!);
    }

    const jitter = stddev(this.stepLengthsPx);
    const elapsedS = Math.max(0.001, (now - this.startTime) / 1000);
    const samplesPerSecondEst = this.mouseSpeeds.length / elapsedS;

    const typing: TypingSignals = {
      avg_inter_key_ms: mean(this.interKeyIntervals),
      std_inter_key_ms: stddev(this.interKeyIntervals),
      median_inter_key_ms: median(this.interKeyIntervals),
      avg_hold_ms: mean(this.keyHoldDurations),
      key_count: this.interKeyIntervals.length + (this.lastKeydownTime !== null ? 1 : 0),
      hesitation_events_gt_500ms: typingHesitationCount(this.interKeyIntervals, 500),
    };

    const mouse: MouseSignals = {
      avg_speed_px_ms: mean(this.mouseSpeeds),
      std_speed_px_ms: stddev(this.mouseSpeeds),
      click_count: this.clickTimestamps.length,
      avg_click_interval_ms: mean(clickIntervals),
      samples_per_second_est: samplesPerSecondEst,
      path_jitter_px: jitter,
      path_length_px: this.mousePathDistAcc,
    };

    const scroll: ScrollSignals = {
      total_scrolls: this.totalScrolls,
      direction_changes: this.scrollDirectionChanges,
      avg_speed: mean(this.scrollSpeeds),
    };

    const touch: TouchSignals = {
      avg_force: mean(this.touchForces),
      touch_count: this.touchCount,
      touchstroke_count: this.touchstrokes,
      curve_length_px: this._lastTouchCurveLen,
      curve_speed_variance: this._lastTouchSpeedVar,
    };

    const session: SessionSignals = {
      time_to_first_interaction_ms:
        this.firstInteractionTime !== null ? this.firstInteractionTime - this.startTime : -1,
      total_active_ms: this.totalActiveMs,
      idle_count: this.idleCount,
      paste_count: this.pasteCount,
      tab_switches: this.tabSwitches,
    };

    const bot_indicators: BotIndicators = {
      zero_mouse_movement:
        mouse.click_count > 3 &&
        mouse.path_jitter_px === 0 &&
        mouse.avg_speed_px_ms === 0 &&
        mouse.samples_per_second_est < 1,
      constant_typing_speed: typing.std_inter_key_ms < 5 && typing.key_count > 20,
      no_scroll: sessionDurationMs > 10_000 && this.totalScrolls === 0,
      suspiciously_fast:
        typing.avg_inter_key_ms > 0 && typing.avg_inter_key_ms < 30 && typing.key_count > 50,
    };

    return { typing, mouse, scroll, touch, session, bot_indicators };
  }

  destroy(): void {
    for (const { target, type, handler } of this.listeners) {
      target.removeEventListener(type, handler);
    }
    this.listeners = [];

    if (this.idleTimer !== null) {
      clearInterval(this.idleTimer);
      this.idleTimer = null;
    }
    if (this.rafId !== null) {
      if (typeof cancelAnimationFrame !== "undefined") {
        cancelAnimationFrame(this.rafId);
      } else {
        clearTimeout(this.rafId);
      }
      this.rafId = null;
    }
    if (this.mouseWorker) {
      this.mouseWorker.terminate();
      this.mouseWorker = null;
    }
  }
}
