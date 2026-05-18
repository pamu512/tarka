import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";

import {
  integrations,
  type RegionalRiskCountryGroup,
  type RegionalRiskSubRegion,
  type RegionalRiskTogglesResponse,
} from "../api/client";
import { RegionalRiskBlacklistBadge } from "../components/compliance/RegionalRiskBlacklistBadge";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

function tierTone(tier: string): string {
  if (tier === "critical") return "text-rose-300";
  if (tier === "elevated") return "text-amber-300";
  return "text-gray-400";
}

export default function RegionalRiskToggles(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<RegionalRiskTogglesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [onlyBlacklisted, setOnlyBlacklisted] = useState(false);

  useRegisterPageMeta({ title: "Regional risk", subtitle: "Sub-region blacklists" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.regionalRiskToggles({ tenant_id: tenantId });
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Regional risk", action: "load toggles" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = useCallback(
    async (row: RegionalRiskSubRegion, blacklisted: boolean) => {
      setBusyId(row.sub_region_id);
      try {
        const res = await integrations.regionalRiskToggle({
          tenant_id: tenantId,
          sub_region_id: row.sub_region_id,
          blacklisted,
        });
        setData(res.board);
        setError(null);
      } catch (e) {
        setError(toUserFacingError(e, { subject: "Regional risk", action: "update blacklist" }));
      } finally {
        setBusyId(null);
      }
    },
    [tenantId],
  );

  const groups = useMemo(() => {
    const all = data?.country_groups ?? [];
    if (!onlyBlacklisted) return all;
    return all
      .map((g) => ({
        ...g,
        sub_regions: g.sub_regions.filter((s) => s.blacklisted),
      }))
      .filter((g) => g.sub_regions.length > 0);
  }, [data, onlyBlacklisted]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="compliance">Regional risk toggles</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Blacklist specific <strong className="text-gray-300">sub-regions</strong> during coordinated attack
            waves. Blacklisted areas block new onboarding and outbound payouts until analysts clear the toggle.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET/PATCH /api/ingress/v1/compliance/regional-risk-toggles
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Loading regional risk map…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Sub-regions" value={data.summary.sub_region_count} />
            <Stat label="Blacklisted" value={data.summary.blacklisted_count} accent="rose" />
            <Stat label="Critical waves" value={data.summary.critical_wave_count} />
            <Stat label="Elevated waves" value={data.summary.elevated_wave_count} />
          </div>

          {data.signals.length > 0 ? (
            <ul className="rounded-xl border border-rose-500/25 bg-rose-950/10 px-4 py-3 text-sm text-rose-100/90 list-disc pl-5 space-y-1">
              {data.signals.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : null}

          <label className="inline-flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={onlyBlacklisted}
              onChange={(e) => setOnlyBlacklisted(e.target.checked)}
              className="rounded border-surface-600"
            />
            Show blacklisted only
          </label>

          <div className="space-y-4">
            {groups.map((group) => (
              <CountryGroupCard
                key={group.country_code}
                group={group}
                busyId={busyId}
                onToggle={toggle}
                warn={data.thresholds.attack_wave_warn}
                critical={data.thresholds.attack_wave_critical}
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}): ReactElement {
  const tone =
    accent === "rose" ? "border-rose-500/35 bg-rose-950/20" : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">{value}</p>
    </div>
  );
}

function CountryGroupCard({
  group,
  busyId,
  onToggle,
  warn,
  critical,
}: {
  group: RegionalRiskCountryGroup;
  busyId: string | null;
  onToggle: (row: RegionalRiskSubRegion, blacklisted: boolean) => void;
  warn: number;
  critical: number;
}): ReactElement {
  return (
    <section className="rounded-xl border border-surface-700 overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-700 flex justify-between items-center bg-surface-900/60">
        <h2 className="text-sm font-semibold text-gray-200">
          {group.country_name}{" "}
          <span className="font-mono text-gray-500 text-xs">{group.country_code}</span>
        </h2>
        <span className="text-[11px] text-gray-500">{group.blacklisted_count} blacklisted</span>
      </div>
      <ul className="divide-y divide-surface-800">
        {group.sub_regions.map((row) => (
          <li key={row.sub_region_id} className="px-4 py-3 flex flex-wrap items-center gap-4 hover:bg-surface-900/30">
            <div className="flex-1 min-w-[200px]">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm text-gray-200">{row.label}</p>
                {row.blacklisted ? <RegionalRiskBlacklistBadge label={row.label} /> : null}
              </div>
              <p className="text-[10px] font-mono text-gray-600 mt-0.5">{row.sub_region_id}</p>
              <p className={`text-[10px] mt-1 ${tierTone(row.attack_tier)}`}>
                Attack wave {row.attack_wave_score} · {row.incidents_24h} incidents/24h · warn≥{warn} critical≥
                {critical}
              </p>
              {row.signals.length > 0 ? (
                <p className="text-[9px] text-gray-500 mt-0.5">{row.signals.join(" · ")}</p>
              ) : null}
            </div>
            <label className="inline-flex items-center gap-2 text-xs text-gray-400 shrink-0 cursor-pointer">
              <input
                type="checkbox"
                checked={row.blacklisted}
                disabled={busyId === row.sub_region_id}
                onChange={(e) => void onToggle(row, e.target.checked)}
                className="rounded border-surface-600 w-4 h-4"
              />
              Blacklist
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}
