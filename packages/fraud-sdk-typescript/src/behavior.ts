export interface TypingSignals {
  avg_inter_key_ms: number;
  std_inter_key_ms: number;
  avg_hold_ms: number;
  key_count: number;
}

export interface MouseSignals {
  avg_speed_px_ms: number;
  std_speed_px_ms: number;
  click_count: number;
  avg_click_interval_ms: number;
}

export interface ScrollSignals {
  total_scrolls: number;
  direction_changes: number;
  avg_speed: number;
}

export interface TouchSignals {
  avg_force: number;
  touch_count: number;
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
  private lastMousePos: { x: number; y: number; t: number } | null = null;
  private mouseSampleTimer: number | null = null;
  private pendingMousePos: { x: number; y: number; t: number } | null = null;

  private listeners: Array<{
    target: EventTarget;
    type: string;
    handler: EventListener;
  }> = [];

  constructor() {
    this.startTime = Date.now();
    this.lastActivityTime = this.startTime;

    if (typeof document === "undefined" || typeof window === "undefined") return;

    this.addListener(document, "keydown", this.onKeydown);
    this.addListener(document, "keyup", this.onKeyup);
    this.addListener(document, "mousemove", this.onMousemove);
    this.addListener(document, "click", this.onClick);
    this.addListener(document, "scroll", this.onScroll, true);
    this.addListener(document, "touchstart", this.onTouchstart);
    this.addListener(document, "touchend", this.onTouchend);
    this.addListener(document, "paste", this.onPaste);
    this.addListener(document, "visibilitychange", this.onVisibilitychange);

    this.idleTimer = setInterval(() => this.checkIdle(), 1000);
  }

  private addListener(
    target: EventTarget,
    type: string,
    handler: (e: Event) => void,
    capture = false,
  ): void {
    const bound = handler.bind(this) as EventListener;
    target.addEventListener(type, bound, { passive: true, capture });
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

  private onKeydown(e: Event): void {
    this.recordActivity();
    const ke = e as KeyboardEvent;
    const now = Date.now();

    if (this.lastKeydownTime !== null) {
      const interval = now - this.lastKeydownTime;
      this.interKeyIntervals.push(interval);
      if (this.interKeyIntervals.length > 50) {
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
    this.pendingMousePos = { x: me.clientX, y: me.clientY, t: Date.now() };

    if (this.mouseSampleTimer === null) {
      this.mouseSampleTimer = window.setTimeout(() => {
        this.sampleMouseSpeed();
        this.mouseSampleTimer = null;
      }, 50);
    }
  }

  private sampleMouseSpeed(): void {
    if (!this.pendingMousePos) return;
    const cur = this.pendingMousePos;

    if (this.lastMousePos) {
      const dx = cur.x - this.lastMousePos.x;
      const dy = cur.y - this.lastMousePos.y;
      const dt = cur.t - this.lastMousePos.t;
      if (dt > 0) {
        const dist = Math.sqrt(dx * dx + dy * dy);
        const speed = dist / dt;
        this.mouseSpeeds.push(speed);
        if (this.mouseSpeeds.length > 100) {
          this.mouseSpeeds.shift();
        }
      }
    }
    this.lastMousePos = cur;
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
      this.lastScrollDirection === null
        ? "down"
        : scrollTop >= 0
          ? "down"
          : "up";

    if (this.lastScrollDirection !== null && direction !== this.lastScrollDirection) {
      this.scrollDirectionChanges++;
    }
    this.lastScrollDirection = direction;

    this.scrollSpeeds.push(Math.abs(scrollTop));
  }

  private onTouchstart(e: Event): void {
    this.recordActivity();
    this.touchCount++;
    const te = e as TouchEvent;
    if (te.touches && te.touches.length > 0) {
      const force = (te.touches[0] as any).force;
      if (typeof force === "number" && force > 0) {
        this.touchForces.push(force);
        if (this.touchForces.length > 20) {
          this.touchForces.shift();
        }
      }
    }
  }

  private onTouchend(): void {
    this.recordActivity();
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

    const keyCount =
      this.interKeyIntervals.length + (this.lastKeydownTime !== null ? 1 : 0);

    const clickIntervals: number[] = [];
    for (let i = 1; i < this.clickTimestamps.length; i++) {
      clickIntervals.push(this.clickTimestamps[i] - this.clickTimestamps[i - 1]);
    }

    const typing: TypingSignals = {
      avg_inter_key_ms: mean(this.interKeyIntervals),
      std_inter_key_ms: stddev(this.interKeyIntervals),
      avg_hold_ms: mean(this.keyHoldDurations),
      key_count: keyCount,
    };

    const mouse: MouseSignals = {
      avg_speed_px_ms: mean(this.mouseSpeeds),
      std_speed_px_ms: stddev(this.mouseSpeeds),
      click_count: this.clickTimestamps.length,
      avg_click_interval_ms: mean(clickIntervals),
    };

    const scroll: ScrollSignals = {
      total_scrolls: this.totalScrolls,
      direction_changes: this.scrollDirectionChanges,
      avg_speed: mean(this.scrollSpeeds),
    };

    const touch: TouchSignals = {
      avg_force: mean(this.touchForces),
      touch_count: this.touchCount,
    };

    const session: SessionSignals = {
      time_to_first_interaction_ms:
        this.firstInteractionTime !== null
          ? this.firstInteractionTime - this.startTime
          : -1,
      total_active_ms: this.totalActiveMs,
      idle_count: this.idleCount,
      paste_count: this.pasteCount,
      tab_switches: this.tabSwitches,
    };

    const bot_indicators: BotIndicators = {
      zero_mouse_movement:
        mouse.click_count > 5 && mouse.avg_speed_px_ms === 0,
      constant_typing_speed:
        typing.std_inter_key_ms < 5 && typing.key_count > 20,
      no_scroll: sessionDurationMs > 10_000 && this.totalScrolls === 0,
      suspiciously_fast:
        typing.avg_inter_key_ms > 0 &&
        typing.avg_inter_key_ms < 30 &&
        typing.key_count > 50,
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
    if (this.mouseSampleTimer !== null) {
      clearTimeout(this.mouseSampleTimer);
      this.mouseSampleTimer = null;
    }
  }
}
