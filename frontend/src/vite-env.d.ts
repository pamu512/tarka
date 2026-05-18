/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** Defaults to `/api/auth/refresh` (same-origin unless absolute). */
  readonly VITE_AUTH_REFRESH_URL?: string;
  /** `bearer` (sessionStorage tokens) or `cookie` (refresh via `withCredentials`). */
  readonly VITE_AUTH_MODE?: string;
  /** Force `withCredentials: true` on the Axios instance (e.g. cross-site cookie sessions). */
  readonly VITE_AUTH_WITH_CREDENTIALS?: string;
  /** Cooldown after a 5xx before new requests are allowed again (ms). Default 30000. */
  readonly VITE_HTTP_CIRCUIT_COOLDOWN_MS?: string;
  /** GraphQL HTTP endpoint for Apollo Client (defaults to `/graphql`). */
  readonly VITE_GRAPHQL_URI?: string;
  /** Health probe URL when runtime tier is `micro`. */
  readonly VITE_HEALTH_URL_MICRO?: string;
  /** Health probe URL when runtime tier is `production`. */
  readonly VITE_HEALTH_URL_PRODUCTION?: string;
  /** JWT / OIDC claim name for role list (default `roles`; mirrors backend `OIDC_ROLES_CLAIM`). */
  readonly VITE_OIDC_ROLES_CLAIM?: string;
  /** WebSocket URL for the live transaction grid (`/transactions/live`); optional. */
  readonly VITE_TRANSACTIONS_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
