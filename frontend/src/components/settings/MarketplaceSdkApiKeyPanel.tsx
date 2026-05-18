import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type MarketplaceSdkApiKeyRecord,
  type MarketplaceSdkPlatform,
} from "@/api/client";
import { useTenantEnvironment } from "@/context/TenantEnvironmentContext";
import { toUserFacingError } from "@/utils/userFacingErrors";

const PLATFORM_LABEL: Record<string, string> = {
  "sdk-python": "Python (Duta)",
  "sdk-typescript": "TypeScript (Darpana)",
  "sdk-android": "Android (Kavacha)",
  "sdk-ios": "iOS (Mudra)",
  "sdk-web": "Web (Anumana)",
};

export function MarketplaceSdkApiKeyPanel(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [platforms, setPlatforms] = useState<MarketplaceSdkPlatform[]>([]);
  const [allowedScopes, setAllowedScopes] = useState<string[]>([]);
  const [keys, setKeys] = useState<MarketplaceSdkApiKeyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [newPlatform, setNewPlatform] = useState("sdk-typescript");
  const [newLabel, setNewLabel] = useState("");
  const [newScopes, setNewScopes] = useState<string[]>([]);
  const [issuedSecret, setIssuedSecret] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, listed] = await Promise.all([
        integrations.marketplaceSdkApiKeysCatalog(),
        integrations.marketplaceSdkApiKeysList(tenantId),
      ]);
      setPlatforms(catalog.platforms);
      setAllowedScopes(catalog.allowed_scopes);
      setKeys(listed.keys);
      setError(null);
      if (catalog.platforms.length && !catalog.platforms.some((p) => p.id === newPlatform)) {
        setNewPlatform(catalog.platforms[0]?.id ?? "sdk-typescript");
      }
    } catch (e) {
      setError(toUserFacingError(e, { subject: "SDK API keys", action: "load keys" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedPlatform = useMemo(
    () => platforms.find((p) => p.id === newPlatform),
    [platforms, newPlatform],
  );

  useEffect(() => {
    if (selectedPlatform && newScopes.length === 0) {
      setNewScopes([...selectedPlatform.default_scopes]);
    }
  }, [selectedPlatform, newScopes.length]);

  const toggleScope = (scope: string) => {
    setNewScopes((prev) => (prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]));
  };

  const createKey = async () => {
    setBusy(true);
    setIssuedSecret(null);
    try {
      const res = await integrations.marketplaceSdkApiKeysCreate({
        tenant_id: tenantId,
        platform: newPlatform,
        label: newLabel || `${PLATFORM_LABEL[newPlatform] ?? newPlatform} key`,
        scopes: newScopes,
      });
      setIssuedSecret(res.secret);
      setNewLabel("");
      await load();
    } catch (e) {
      setError(toUserFacingError(e, { subject: "SDK API key", action: "create key" }));
    } finally {
      setBusy(false);
    }
  };

  const revokeKey = async (row: MarketplaceSdkApiKeyRecord) => {
    if (row.status === "revoked") return;
    if (!window.confirm(`Revoke ${row.label} (${row.key_prefix})? SDK clients using this key will fail.`)) return;
    setBusy(true);
    try {
      await integrations.marketplaceSdkApiKeysRevoke(row.id, tenantId);
      await load();
    } catch (e) {
      setError(toUserFacingError(e, { subject: "SDK API key", action: "revoke key" }));
    } finally {
      setBusy(false);
    }
  };

  const copySecret = async () => {
    if (!issuedSecret) return;
    try {
      await navigator.clipboard.writeText(issuedSecret);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900/80 p-4 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-200">Marketplace SDK API keys</h2>
        <p className="text-xs text-gray-500 mt-1 leading-relaxed">
          Programmatic keys for{" "}
          <span className="text-gray-400">Python, TypeScript, Android, iOS, and Web</span> SDKs. Pass as{" "}
          <code className="text-gray-400">X-API-Key</code> or <code className="text-gray-400">TARKA_API_KEY</code> in
          your app. Secrets are shown once at creation. Configure per-key{" "}
          <Link to="/integrations/rate-limit-shields" className="text-brand-400 hover:text-brand-300 font-medium">
            rate limit shields
          </Link>{" "}
          to auto-throttle abusive traffic.
        </p>
      </div>

      {error ? <p className="text-xs text-rose-300/90">{error}</p> : null}

      {issuedSecret ? (
        <div className="rounded-lg border border-emerald-500/35 bg-emerald-950/25 px-3 py-3 space-y-2">
          <p className="text-xs font-semibold text-emerald-200">New key — copy now</p>
          <code className="block text-[11px] font-mono text-emerald-100 break-all">{issuedSecret}</code>
          <button
            type="button"
            onClick={() => void copySecret()}
            className="text-xs text-brand-300 hover:text-brand-200"
          >
            Copy to clipboard
          </button>
        </div>
      ) : null}

      <div className="rounded-lg border border-surface-700 bg-surface-950/50 p-3 space-y-3">
        <p className="text-[11px] uppercase tracking-wide text-gray-500">Issue key</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-gray-500 block">
            SDK
            <select
              value={newPlatform}
              onChange={(e) => {
                setNewPlatform(e.target.value);
                setNewScopes([]);
              }}
              className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-2 py-1.5 text-gray-200 text-sm"
            >
              {platforms.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.codename})
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-500 block">
            Label
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Production mobile"
              className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-2 py-1.5 text-gray-200 text-sm"
            />
          </label>
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1.5">Scopes</p>
          <div className="flex flex-wrap gap-2">
            {allowedScopes.map((scope) => (
              <label
                key={scope}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] cursor-pointer ${
                  newScopes.includes(scope)
                    ? "border-brand-500/50 bg-brand-950/40 text-brand-200"
                    : "border-surface-600 text-gray-400"
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={newScopes.includes(scope)}
                  onChange={() => toggleScope(scope)}
                />
                {scope}
              </label>
            ))}
          </div>
        </div>
        <button
          type="button"
          disabled={busy || newScopes.length === 0}
          onClick={() => void createKey()}
          className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 px-3 py-1.5 text-xs font-semibold text-white"
        >
          {busy ? "Issuing…" : "Issue API key"}
        </button>
      </div>

      {loading ? (
        <p className="text-xs text-gray-500">Loading keys…</p>
      ) : keys.length === 0 ? (
        <p className="text-xs text-gray-500">No keys for tenant <span className="font-mono">{tenantId}</span>.</p>
      ) : (
        <ul className="divide-y divide-surface-800 border border-surface-700 rounded-lg overflow-hidden">
          {keys.map((row) => (
            <li key={row.id} className="px-3 py-2.5 flex flex-wrap items-center gap-2 text-xs">
              <div className="flex-1 min-w-[180px]">
                <p className="font-medium text-gray-200">{row.label}</p>
                <p className="font-mono text-[11px] text-gray-500 mt-0.5">
                  {PLATFORM_LABEL[row.platform] ?? row.platform} · {row.key_prefix}
                </p>
                <p className="text-[10px] text-gray-600 mt-0.5">
                  {row.scopes.join(", ")}
                  {row.last_used_at ? ` · last used ${new Date(row.last_used_at).toLocaleString()}` : ""}
                </p>
              </div>
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${
                  row.status === "active"
                    ? "border-emerald-500/35 text-emerald-200"
                    : "border-surface-600 text-gray-500"
                }`}
              >
                {row.status}
              </span>
              {row.status === "active" ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void revokeKey(row)}
                  className="rounded border border-rose-500/40 px-2 py-1 text-[11px] text-rose-200 hover:bg-rose-950/30"
                >
                  Revoke
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
