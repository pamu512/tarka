import { useEffect, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";

import { leanHomePath } from "@/config/leanNav";

type AuthConfig = {
  oidc_enabled: boolean;
};

function safeNext(raw: string | null): string {
  if (!raw) return leanHomePath();
  const value = raw.trim();
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return leanHomePath();
  }
  return value;
}

function detailFromBody(text: string): string | null {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail.trim();
    }
  } catch {
    /* keep generic */
  }
  return null;
}

export default function Login(): ReactElement {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/auth/config", { headers: { Accept: "application/json" } });
        const text = await res.text();
        if (cancelled) return;
        if (res.status === 503) {
          setError(detailFromBody(text) || "SSO is misconfigured (OIDC_CLIENT_ID required).");
          setConfig(null);
          return;
        }
        if (!res.ok) {
          setError(detailFromBody(text) || `Could not load auth config (HTTP ${res.status}).`);
          setConfig(null);
          return;
        }
        const parsed = JSON.parse(text) as AuthConfig;
        setConfig({ oidc_enabled: Boolean(parsed.oidc_enabled) });
        setError(null);
      } catch {
        if (!cancelled) {
          setError("Could not reach the auth service.");
          setConfig(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const ssoHref = `/api/auth/login?next=${encodeURIComponent(next)}`;

  return (
    <div className="mx-auto max-w-lg px-6 py-16 space-y-5">
      <h1 className="text-2xl font-semibold text-gray-100">Sign in</h1>
      {loading ? (
        <p className="text-sm text-gray-400">Checking how this desk authenticates…</p>
      ) : null}
      {error ? (
        <p className="text-sm text-rose-300" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && config?.oidc_enabled ? (
        <div className="space-y-3">
          <p className="text-sm text-gray-400">
            This desk uses your organization identity provider. Tokens stay on the server until
            the callback finishes — they are not placed on the URL.
          </p>
          <a
            href={ssoHref}
            className="inline-flex items-center justify-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 transition-colors"
          >
            Sign in with SSO
          </a>
        </div>
      ) : null}
      {!loading && config && !config.oidc_enabled ? (
        <div className="space-y-3 text-sm text-gray-400">
          <p>
            Local mode — SSO is not configured on this desk (<code className="text-gray-300">OIDC_ISSUER</code>{" "}
            is empty). Use existing local credentials:{" "}
            <code className="text-gray-300">ALLOW_INSECURE_NO_AUTH</code> or{" "}
            <code className="text-gray-300">API_KEYS</code> still apply.
          </p>
          <Link
            to={next}
            className="inline-flex items-center justify-center rounded-md bg-surface-700 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-surface-600 transition-colors"
          >
            Continue to desk
          </Link>
        </div>
      ) : null}
    </div>
  );
}

