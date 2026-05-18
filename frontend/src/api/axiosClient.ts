import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
  isAxiosError,
} from "axios";

import {
  dispatchSessionExpired,
  getAccessToken,
  getRefreshToken,
  setSessionTokens,
} from "./authSession";
import {
  getHttpCircuitDeadline,
  HttpCircuitOpenError,
  isHttpCircuitOpen,
  recordHttp5xxResponse,
  recordHttpSuccess,
} from "./httpCircuitBreaker";

function resolveBaseURL(): string {
  const v = import.meta.env.VITE_API_BASE_URL;
  if (typeof v === "string" && v.trim()) {
    return v.trim().replace(/\/$/, "");
  }
  return "";
}

function resolveRefreshUrl(): string {
  const v = import.meta.env.VITE_AUTH_REFRESH_URL;
  if (typeof v === "string" && v.trim()) {
    return v.trim();
  }
  return "/api/auth/refresh";
}

function authMode(): "bearer" | "cookie" {
  const m = import.meta.env.VITE_AUTH_MODE?.trim().toLowerCase();
  return m === "cookie" ? "cookie" : "bearer";
}

function withCredentialsDefault(): boolean {
  return authMode() === "cookie" || import.meta.env.VITE_AUTH_WITH_CREDENTIALS === "true";
}

function parseRefreshBody(data: unknown): { access: string; refresh: string | null } | null {
  if (data === null || typeof data !== "object") {
    return null;
  }
  const o = data as Record<string, unknown>;
  const accessRaw =
    (typeof o.access_token === "string" && o.access_token) ||
    (typeof o.accessToken === "string" && o.accessToken) ||
    "";
  const access = accessRaw.trim();
  if (!access) {
    return null;
  }
  let refresh: string | null = null;
  if (typeof o.refresh_token === "string" && o.refresh_token.trim()) {
    refresh = o.refresh_token.trim();
  } else if (typeof o.refreshToken === "string" && o.refreshToken.trim()) {
    refresh = o.refreshToken.trim();
  }
  return { access, refresh };
}

let refreshInFlight: Promise<void> | null = null;

async function refreshSessionWithPlainClient(plain: AxiosInstance): Promise<void> {
  const mode = authMode();
  const url = resolveRefreshUrl();
  if (mode === "bearer") {
    const rt = getRefreshToken();
    if (!rt) {
      dispatchSessionExpired("missing_tokens");
      throw new AxiosError("Missing refresh token", "ERR_BAD_REQUEST", undefined, undefined, undefined);
    }
    const res = await plain.post<unknown>(url, { refresh_token: rt });
    if (res.status !== 200 && res.status !== 201) {
      dispatchSessionExpired("refresh_failed");
      throw new AxiosError(
        "Token refresh rejected",
        AxiosError.ERR_BAD_RESPONSE,
        res.config,
        res.request,
        res,
      );
    }
    const parsed = parseRefreshBody(res.data);
    if (!parsed) {
      dispatchSessionExpired("refresh_failed");
      throw new AxiosError(
        "Token refresh returned no access token",
        AxiosError.ERR_BAD_RESPONSE,
        res.config,
        res.request,
        res,
      );
    }
    const nextRefresh = parsed.refresh ?? getRefreshToken();
    setSessionTokens(parsed.access, nextRefresh);
    return;
  }

  const res = await plain.post<unknown>(url, {});
  if (res.status !== 200 && res.status !== 201) {
    dispatchSessionExpired("refresh_failed");
    throw new AxiosError(
      "Cookie refresh rejected",
      AxiosError.ERR_BAD_RESPONSE,
      res.config,
      res.request,
      res,
    );
  }
  const parsed = parseRefreshBody(res.data);
  if (parsed?.access) {
    setSessionTokens(parsed.access, parsed.refresh ?? getRefreshToken());
  }
}

function isAuthRefreshRequest(config: InternalAxiosRequestConfig): boolean {
  const refreshUrl = resolveRefreshUrl();
  const built = `${config.baseURL ?? ""}${config.url ?? ""}`;
  try {
    const left = new URL(refreshUrl, "http://tarka.local");
    const right = new URL(built.startsWith("http") ? built : `http://tarka.local${built.startsWith("/") ? "" : "/"}${built}`);
    return left.pathname === right.pathname && left.search === right.search;
  } catch {
    return built === refreshUrl || built.endsWith(refreshUrl);
  }
}

/**
 * Typed Axios instance for Tarka APIs: bearer/cookie auth, JWT refresh on 401, and a global
 * circuit breaker driven by 5xx responses ({@link import("./httpCircuitBreaker").TARKA_HTTP_CIRCUIT_OPEN_EVENT}).
 */
export function createTarkaHttpClient(): AxiosInstance {
  const baseURL = resolveBaseURL();
  const instance = axios.create({
    baseURL,
    timeout: 120_000,
    headers: { Accept: "application/json" },
    withCredentials: withCredentialsDefault(),
    validateStatus: (status) => status >= 200 && status < 300,
  });

  const plain = axios.create({
    baseURL,
    timeout: 60_000,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    withCredentials: withCredentialsDefault(),
    validateStatus: (status) => status >= 200 && status < 300,
  });

  instance.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    if (isHttpCircuitOpen()) {
      return Promise.reject(new HttpCircuitOpenError(getHttpCircuitDeadline()));
    }
    const headers = AxiosHeaders.from(config.headers ?? {});
    if (authMode() === "bearer") {
      const t = getAccessToken();
      if (t) {
        headers.set("Authorization", `Bearer ${t}`);
      }
    }
    return { ...config, headers };
  });

  instance.interceptors.response.use(
    (response: AxiosResponse) => {
      recordHttpSuccess();
      return response;
    },
    async (error: unknown) => {
      if (isAxiosError(error)) {
        const st = error.response?.status;
        if (st !== undefined && (st < 500 || st > 599)) {
          recordHttpSuccess();
        }
        if (st !== undefined && st >= 500 && st <= 599) {
          const cfg = error.config;
          recordHttp5xxResponse({
            status: st,
            url: cfg?.url ?? "",
            method: typeof cfg?.method === "string" ? cfg.method.toUpperCase() : "GET",
          });
        }

        const { response, config } = error;
        if (response?.status === 401 && config && !config.skipAuthRefresh) {
          if (isAuthRefreshRequest(config)) {
            dispatchSessionExpired("refresh_failed");
            return Promise.reject(error);
          }
          try {
            if (!refreshInFlight) {
              refreshInFlight = refreshSessionWithPlainClient(plain).finally(() => {
                refreshInFlight = null;
              });
            }
            await refreshInFlight;
            const retryCfg: InternalAxiosRequestConfig = { ...config, skipAuthRefresh: true };
            retryCfg.headers = AxiosHeaders.from(retryCfg.headers ?? {});
            if (authMode() === "bearer") {
              const t = getAccessToken();
              if (t) {
                retryCfg.headers.set("Authorization", `Bearer ${t}`);
              }
            }
            return await instance.request(retryCfg);
          } catch (refreshErr: unknown) {
            const wrapped =
              refreshErr instanceof Error ? refreshErr : new Error(String(refreshErr));
            return Promise.reject(wrapped);
          }
        }
      }
      const fallback = isAxiosError(error)
        ? error
        : error instanceof Error
          ? error
          : new Error(typeof error === "string" ? error : "Request failed");
      return Promise.reject(fallback);
    },
  );

  return instance;
}

/** Shared client for app modules that require interceptors (auth refresh + circuit breaker). */
export const httpClient: AxiosInstance = createTarkaHttpClient();
