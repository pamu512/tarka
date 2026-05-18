export type ResilientWebSocketStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "reconnecting"
  | "error";

export const WS_RECONNECT_BASE_MS = 500;
export const WS_RECONNECT_MAX_MS = 30_000;

/** Exponential backoff delay before the next reconnect attempt (without jitter). */
export function nextReconnectDelayMs(attempt: number): number {
  return Math.min(WS_RECONNECT_MAX_MS, WS_RECONNECT_BASE_MS * 2 ** attempt);
}

function withJitterMs(delayMs: number): number {
  return Math.round(delayMs * (0.85 + Math.random() * 0.3));
}

export type ResilientWebSocketHandlers = {
  readonly onTextMessage: (text: string) => void;
  readonly onStatus?: (status: ResilientWebSocketStatus, detail?: string) => void;
};

/**
 * Browser WebSocket wrapper with automatic reconnect and exponential backoff (capped + jitter).
 */
export class ResilientWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempt = 0;
  private closedByUser = false;
  /** Browser timer id (`window.setTimeout`); avoids Node `Timeout` vs DOM `number` mismatch under `tsc -b`. */
  private reconnectTimer: number | null = null;

  constructor(
    private readonly url: string,
    private readonly handlers: ResilientWebSocketHandlers,
  ) {}

  public connect(): void {
    this.closedByUser = false;
    this.clearReconnectTimer();
    this.openSocket();
  }

  public disconnect(): void {
    this.closedByUser = true;
    this.clearReconnectTimer();
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      try {
        this.ws.close(1000, "client disconnect");
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
    this.handlers.onStatus?.("closed", "client disconnect");
  }

  public sendText(text: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(text);
    }
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.closedByUser) {
      return;
    }
    const base = nextReconnectDelayMs(this.reconnectAttempt);
    const delay = withJitterMs(base);
    this.reconnectAttempt += 1;
    this.handlers.onStatus?.("reconnecting", `in ${delay}ms (attempt ${this.reconnectAttempt})`);
    this.clearReconnectTimer();
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private openSocket(): void {
    if (this.closedByUser) {
      return;
    }
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      return;
    }
    this.handlers.onStatus?.("connecting", this.url);
    try {
      const ws = new WebSocket(this.url);
      this.ws = ws;
      ws.onopen = () => {
        this.reconnectAttempt = 0;
        this.handlers.onStatus?.("open", this.url);
      };
      ws.onmessage = (ev: MessageEvent<string | Blob | ArrayBuffer>) => {
        if (typeof ev.data === "string") {
          this.handlers.onTextMessage(ev.data);
        }
      };
      ws.onerror = () => {
        this.handlers.onStatus?.("error", "socket error");
      };
      ws.onclose = () => {
        this.ws = null;
        this.handlers.onStatus?.("closed", "socket closed");
        if (!this.closedByUser) {
          this.scheduleReconnect();
        }
      };
    } catch (e) {
      this.handlers.onStatus?.("error", e instanceof Error ? e.message : String(e));
      if (!this.closedByUser) {
        this.scheduleReconnect();
      }
    }
  }
}
