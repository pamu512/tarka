import { isAxiosError, type AxiosError } from "axios";

export type GlobalErrorSource = "react" | "unhandledRejection" | "windowError";

export interface GlobalErrorTrace {
  readonly source: GlobalErrorSource;
  readonly capturedAt: string;
  readonly summary: string;
  readonly react?: {
    readonly name: string;
    readonly message: string;
    readonly stack?: string;
  };
  readonly componentStack?: string;
  /** Parsed JSON body from a failed HTTP call when available (e.g. FastAPI `detail` / `error` envelope). */
  readonly httpResponseJson?: unknown;
  readonly httpStatus?: number;
  readonly httpUrl?: string;
  /** Original rejection / error before shaping (still passed through sanitizer for display). */
  readonly raw?: unknown;
}

function tryParseJsonObject(text: string): unknown | null {
  const t = text.trim();
  if (!t.startsWith("{") && !t.startsWith("[")) {
    return null;
  }
  try {
    return JSON.parse(t) as unknown;
  } catch {
    return null;
  }
}

function axiosToTrace(err: AxiosError<unknown>): Partial<GlobalErrorTrace> {
  const status = err.response?.status;
  const httpUrl =
    typeof err.config?.url === "string"
      ? err.config.baseURL
        ? `${String(err.config.baseURL).replace(/\/$/, "")}/${String(err.config.url).replace(/^\//, "")}`
        : err.config.url
      : undefined;
  const data = err.response?.data;
  let httpResponseJson: unknown = data;
  if (typeof data === "string") {
    httpResponseJson = tryParseJsonObject(data) ?? data;
  }
  return {
    httpStatus: status,
    httpUrl,
    httpResponseJson,
    summary: err.message || "HTTP request failed",
  };
}

function errorToReactTrace(err: Error): GlobalErrorTrace["react"] {
  return {
    name: err.name,
    message: err.message,
    stack: err.stack,
  };
}

export function buildErrorTraceFromUnknown(reason: unknown, source: GlobalErrorSource): GlobalErrorTrace {
  const capturedAt = new Date().toISOString();

  if (isAxiosError(reason)) {
    const ax = axiosToTrace(reason);
    return {
      source,
      capturedAt,
      summary: ax.summary ?? "HTTP request failed",
      httpResponseJson: ax.httpResponseJson,
      httpStatus: ax.httpStatus,
      httpUrl: ax.httpUrl,
      raw: {
        axios: true,
        code: reason.code,
        message: reason.message,
      },
    };
  }

  if (reason instanceof Error) {
    return {
      source,
      capturedAt,
      summary: reason.message || reason.name,
      react: errorToReactTrace(reason),
      raw: { name: reason.name, message: reason.message, stack: reason.stack },
    };
  }

  if (typeof reason === "string") {
    const parsed = tryParseJsonObject(reason);
    return {
      source,
      capturedAt,
      summary: reason.slice(0, 200),
      httpResponseJson: parsed ?? undefined,
      raw: reason,
    };
  }

  if (reason !== null && typeof reason === "object") {
    const obj = reason as Record<string, unknown>;
    const msg =
      (typeof obj.message === "string" && obj.message) ||
      (typeof obj.detail === "string" && obj.detail) ||
      "Unhandled error object";
    return {
      source,
      capturedAt,
      summary: msg,
      httpResponseJson: obj,
      raw: reason,
    };
  }

  return {
    source,
    capturedAt,
    summary: String(reason),
    raw: reason,
  };
}

export function mergeReactBoundaryFields(
  base: GlobalErrorTrace,
  error: unknown,
  componentStack: string | null | undefined,
): GlobalErrorTrace {
  const err =
    error instanceof Error
      ? error
      : new Error(typeof error === "string" ? error : `Non-error throw: ${String(error)}`);
  return {
    ...base,
    summary: err.message || base.summary,
    react: errorToReactTrace(err),
    ...(componentStack ? { componentStack } : {}),
    raw: {
      boundary: true,
      inner: base.raw ?? null,
    },
  };
}
