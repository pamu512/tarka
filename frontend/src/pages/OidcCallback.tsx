import { useEffect, useState, type ReactElement } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { leanHomePath } from "@/config/leanNav";

function safeNext(raw: string | null | undefined): string {
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

export default function OidcCallback(): ReactElement {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ticket = params.get("ticket")?.trim() ?? "";
    if (!ticket) {
      setError("Missing one-time ticket. Start again from Sign in.");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/auth/session", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ ticket }),
          credentials: "include",
        });
        const text = await res.text();
        if (cancelled) return;
        if (!res.ok) {
          setError(detailFromBody(text) || `Session exchange failed (HTTP ${res.status}).`);
          return;
        }
        const parsed = JSON.parse(text) as {
          authenticated?: boolean;
          next?: string;
        };
        navigate(safeNext(parsed.next ?? params.get("next")), { replace: true });
      } catch {
        if (!cancelled) setError("Could not complete sign-in.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate, params]);

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-6 py-16 space-y-4">
        <h1 className="text-2xl font-semibold text-gray-100">Sign-in failed</h1>
        <p className="text-sm text-rose-300" role="alert">
          {error}
        </p>
        <Link
          to="/login"
          className="inline-flex items-center justify-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 transition-colors"
        >
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg px-6 py-16 space-y-3">
      <h1 className="text-2xl font-semibold text-gray-100">Completing sign-in</h1>
      <p className="text-sm text-gray-400">Exchanging the one-time ticket for a desk session…</p>
    </div>
  );
}

