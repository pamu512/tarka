import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type MarketplaceRateLimitShieldItem,
  type MarketplaceRateLimitShieldsResponse,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 10_000;
const RPM_PRESETS = [120, 600, 1200, 6000] as const;

const PLATFORM_LABEL: Record<string, string> = {
  "sdk-python": "Python",
  "sdk-typescript": "TypeScript",
  "sdk-android": "Android",
  "sdk-ios": "iOS",
  "sdk-web": "Web",
};

type Draft = {
  enabled: boolean;
  requests_per_minute: number;
  burst: number;
};

function draftFromItem(item: MarketplaceRateLimitShieldItem): Draft {
  return {
    enabled: item.shield.enabled,
    requests_per_minute: item.shield.requests_per_minute,
    burst: item.shield.burst,
  };
}

function draftsEqual(a: Draft, b: Draft): boolean {
  return a.enabled === b.enabled && a.requests_per_minute === b.requests_per_minute && a.burst === b.burst;
}

export default function RateLimitShields(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<MarketplaceRateLimitShieldsResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);

  useRegisterPageMeta({ title: "Rate limit shields", subtitle: "Per API key throttling" });

  const load = useCallback(
    async (silent: boolean) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      try {
        const res = await integrations.marketplaceRateLimitShields(tenantId);
        setData(res);
        setDrafts((prev) => {
          const next: Record<string, Draft> = {};
          for (const item of res.items) {
            const existing = prev[item.key_id];
            next[item.key_id] =
              existing && !draftsEqual(existing, draftFromItem(item)) ? existing : draftFromItem(item);
          }
          return next;
        });
        setError(null);
      } catch (e) {
        if (!silent) setData(null);
        setError(toUserFacingError(e, { subject: "Rate limit shields", action: "load shields" }));
      } finally {
        if (silent) setRefreshing(false);
        else setLoading(false);
      }
    },
    [tenantId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const summary = data?.summary;
  const throttledCount = summary?.throttled ?? 0;

  const updateDraft = (keyId: string, patch: Partial<Draft>) => {
    setDrafts((prev) => ({ ...prev, [keyId]: { ...prev[keyId], ...patch } }));
  };

  const saveShield = async (item: MarketplaceRateLimitShieldItem) => {
    const draft = drafts[item.key_id];
    if (!draft || draftsEqual(draft, draftFromItem(item))) return;
    setSavingId(item.key_id);
    try {
      await integrations.marketplaceRateLimitShieldUpdate(item.key_id, {
        tenant_id: tenantId,
        enabled: draft.enabled,
        requests_per_minute: draft.requests_per_minute,
        burst: draft.burst,
      });
      await load(true);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Rate limit shield", action: "save limits" }));
    } finally {
      setSavingId(null);
    }
  };

  const dirtyKeys = useMemo(() => {
    if (!data) return new Set<string>();
    const out = new Set<string>();
    for (const item of data.items) {
      const d = drafts[item.key_id];
      if (d && !draftsEqual(d, draftFromItem(item))) out.add(item.key_id);
    }
    return out;
  }, [data, drafts]);

  return (
    <div className="p-6 flex flex-col gap-5 min-h-[calc(100vh-4rem)] animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4 max-w-5xl">
        <div>
          <PageTitle module="integrations">Rate limit shields</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Configure how many requests each marketplace SDK API key may send per minute before{" "}
            <strong className="text-amber-300">auto-throttling</strong> (HTTP 429). Burst allows short spikes;
            sustained traffic over the limit triggers a cooldown.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            PATCH /api/ingress/v1/marketplace/rate-limit-shields/{"{key_id}"}
            {refreshing ? " · refreshing…" : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <Link to="/settings" className="text-xs text-brand-400 hover:text-brand-300">
            SDK API keys →
          </Link>
          <button
            type="button"
            onClick={() => void load(true)}
            className="rounded-lg border border-surface-600 bg-surface-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-surface-700"
          >
            Refresh
          </button>
        </div>
      </div>

      {summary ? (
        <div className="flex flex-wrap gap-3 max-w-3xl">
          <StatPill label="Shields enabled" value={summary.shields_enabled} tone="ok" />
          <StatPill label="Currently throttled" value={summary.throttled} tone={summary.throttled > 0 ? "bad" : "ok"} />
          <StatPill label="Keys" value={data?.count ?? 0} tone="neutral" />
        </div>
      ) : null}

      <p className="text-[11px] text-gray-600">
        Tenant <span className="font-mono text-gray-400">{tenantId}</span>
        {throttledCount > 0 ? (
          <span className="text-amber-300/90"> · {throttledCount} key(s) in throttle cooldown</span>
        ) : null}
      </p>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 max-w-3xl">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-8">Loading rate limit shields…</p>
      ) : data && data.items.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 rounded-xl border border-surface-700 bg-surface-900/50 px-4 max-w-2xl">
          No SDK API keys for this tenant.{" "}
          <Link to="/settings" className="text-brand-400 hover:text-brand-300">
            Issue a key in Settings
          </Link>{" "}
          first.
        </p>
      ) : data ? (
        <ul className="space-y-3 max-w-5xl">
          {data.items.map((item) => {
            const draft = drafts[item.key_id] ?? draftFromItem(item);
            const dirty = dirtyKeys.has(item.key_id);
            const pct =
              item.shield.burst > 0
                ? Math.min(100, Math.round((item.live.requests_in_window / item.shield.burst) * 100))
                : 0;
            return (
              <li
                key={item.key_id}
                className={`rounded-xl border bg-surface-900/70 p-4 space-y-3 ${
                  item.live.throttled ? "border-amber-500/40" : "border-surface-700"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-gray-200">{item.label}</p>
                    <p className="text-[11px] text-gray-500 font-mono mt-0.5">
                      {PLATFORM_LABEL[item.platform] ?? item.platform} · {item.key_prefix}
                      <span
                        className={`ml-2 uppercase text-[10px] font-semibold ${
                          item.status === "active" ? "text-emerald-400" : "text-gray-600"
                        }`}
                      >
                        {item.status}
                      </span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {item.live.throttled ? (
                      <span className="rounded-full border border-amber-500/40 bg-amber-950/40 px-2 py-0.5 text-[10px] font-semibold text-amber-200 uppercase">
                        Throttled
                      </span>
                    ) : null}
                    <label className="inline-flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={draft.enabled}
                        onChange={(e) => updateDraft(item.key_id, { enabled: e.target.checked })}
                        className="rounded border-surface-600"
                      />
                      Shield on
                    </label>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <label className="text-xs text-gray-500 block">
                    Requests / minute
                    <input
                      type="number"
                      min={10}
                      max={100000}
                      value={draft.requests_per_minute}
                      onChange={(e) =>
                        updateDraft(item.key_id, {
                          requests_per_minute: Math.max(10, Number(e.target.value) || 600),
                        })
                      }
                      className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-2 py-1.5 text-gray-200 text-sm font-mono"
                    />
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {RPM_PRESETS.map((rpm) => (
                        <button
                          key={rpm}
                          type="button"
                          onClick={() => updateDraft(item.key_id, { requests_per_minute: rpm })}
                          className="text-[10px] px-1.5 py-0.5 rounded border border-surface-600 text-gray-500 hover:text-gray-300"
                        >
                          {rpm}
                        </button>
                      ))}
                    </div>
                  </label>
                  <label className="text-xs text-gray-500 block">
                    Burst (token bucket)
                    <input
                      type="number"
                      min={1}
                      max={10000}
                      value={draft.burst}
                      onChange={(e) =>
                        updateDraft(item.key_id, { burst: Math.max(1, Number(e.target.value) || 50) })
                      }
                      className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-2 py-1.5 text-gray-200 text-sm font-mono"
                    />
                  </label>
                  <div className="text-xs text-gray-500">
                    Live window
                    <div className="mt-2 space-y-1">
                      <div className="h-2 rounded-full bg-surface-800 overflow-hidden">
                        <div
                          className={`h-full transition-all ${
                            item.live.throttled ? "bg-amber-500" : pct > 80 ? "bg-rose-500" : "bg-brand-500"
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-gray-600 font-mono">
                        {item.live.requests_in_window} used · {item.live.remaining} remaining
                        {item.live.rejected_total > 0 ? ` · ${item.live.rejected_total} rejected` : ""}
                      </p>
                      {item.live.throttled_until ? (
                        <p className="text-[10px] text-amber-400/90">Until {item.live.throttled_until}</p>
                      ) : null}
                    </div>
                  </div>
                </div>

                <div className="flex justify-end">
                  <button
                    type="button"
                    disabled={!dirty || savingId === item.key_id || item.status === "revoked"}
                    onClick={() => void saveShield(item)}
                    className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-40 px-3 py-1.5 text-xs font-semibold text-white"
                  >
                    {savingId === item.key_id ? "Saving…" : dirty ? "Apply shield" : "Saved"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ok" | "bad" | "warn" | "neutral";
}): ReactElement {
  const toneClass =
    tone === "bad"
      ? "border-rose-500/35 text-rose-200"
      : tone === "warn"
        ? "border-amber-500/35 text-amber-200"
        : tone === "neutral"
          ? "border-surface-600 text-gray-300"
          : "border-emerald-500/35 text-emerald-200";
  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
    </div>
  );
}
