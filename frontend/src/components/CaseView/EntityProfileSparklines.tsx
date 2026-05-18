import type { InferenceContext } from "../../api/inferenceContext";
import { buildVelocityHeatmapModel } from "../../utils/velocityHeatmapModel";
import { allocateSpendByHour } from "../../utils/spendVelocitySeries";
import { Sparkline } from "./Sparkline";

export type EntityProfileSparklinesProps = {
  /** Subject entity under investigation (User / Account id). */
  entityId: string;
  inference: InferenceContext | null;
  /** Anchor time for hourly bucket inference (case activity time). */
  anchorIso?: string | null;
  /** Total transaction amount from audit envelope — drives estimated hourly spend curve. */
  cohortSpend?: { amount: number; currency: string } | null;
  /** Last successful refresh of audit / velocity artifacts (ISO). */
  lastUpdatedIso?: string | null;
};

function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency.length === 3 ? currency : "USD",
      maximumFractionDigits: amount >= 100 ? 0 : 2,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

/**
 * Case workspace **subject profile** strip: compact sparklines for estimated spend velocity and raw event velocity (Janus /
 * decision-plane counters). Refreshes when parent re-fetches audit data (polling).
 */
export function EntityProfileSparklines({
  entityId,
  inference,
  anchorIso,
  cohortSpend,
  lastUpdatedIso,
}: EntityProfileSparklinesProps) {
  const model = inference ? buildVelocityHeatmapModel(inference, anchorIso ?? null) : null;
  const buckets = model?.buckets ?? null;

  const spendByHour =
    buckets && cohortSpend && cohortSpend.amount > 0
      ? allocateSpendByHour(buckets, cohortSpend.amount)
      : null;

  const maxSpendHr =
    spendByHour && spendByHour.length > 0 ? Math.max(...spendByHour, 1e-9) : 0;
  const maxEvHr = buckets && buckets.length > 0 ? Math.max(...buckets, 1e-9) : 0;

  const relativeUpdated =
    lastUpdatedIso != null && lastUpdatedIso !== ""
      ? (() => {
          const t = Date.parse(lastUpdatedIso);
          if (!Number.isFinite(t)) return null;
          const s = Math.round((Date.now() - t) / 1000);
          if (s < 60) return `${s}s ago`;
          if (s < 3600) return `${Math.floor(s / 60)}m ago`;
          return new Date(t).toLocaleTimeString();
        })()
      : null;

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-900/85 px-4 py-3"
      aria-label="Subject entity profile, spend velocity sparklines"
      data-testid="entity-profile-sparklines"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-800 pb-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">User profile — velocity</h3>
          <p className="mt-0.5 font-mono text-[11px] text-gray-300 break-all">{entityId}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/40 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <span className="text-[10px] text-gray-500">
            Live refresh
            {relativeUpdated ? (
              <>
                {" "}
                · <span className="text-gray-400">{relativeUpdated}</span>
              </>
            ) : null}
          </span>
        </div>
      </div>

      {!model || !buckets ? (
        <p className="text-xs text-gray-500">
          No inference / velocity payload yet — sparklines appear when the decision audit includes velocity counters.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5 min-w-0">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] font-medium text-gray-400">Spend velocity (est.)</span>
              {cohortSpend && spendByHour ? (
                <span className="text-[10px] tabular-nums text-gray-500">
                  peak {formatMoney(maxSpendHr, cohortSpend.currency)}/h
                </span>
              ) : (
                <span className="text-[10px] text-gray-600">needs txn amount</span>
              )}
            </div>
            <p className="text-[10px] leading-snug text-gray-600">
              Audit amount allocated across UTC hours by event share — proxy for real-time spend pacing.
            </p>
            {spendByHour && cohortSpend ? (
              <Sparkline
                values={spendByHour}
                strokeClassName="stroke-emerald-400"
                fillClassName="fill-emerald-500/20"
                aria-label="Estimated hourly spend trend over 24 UTC hours"
              />
            ) : (
              <div className="h-9 rounded-md border border-dashed border-surface-700 bg-surface-950/50 flex items-center px-2">
                <span className="text-[10px] text-gray-600">Attach cohort amount on audit envelope for USD curve.</span>
              </div>
            )}
          </div>

          <div className="space-y-1.5 min-w-0">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] font-medium text-gray-400">Transaction burst</span>
              <span className="text-[10px] tabular-nums text-gray-500">peak {Math.round(maxEvHr)} evt/h</span>
            </div>
            <p className="text-[10px] leading-snug text-gray-600">
              Rolling 24h event counts per UTC hour
              {model.synthesized ? " — buckets inferred from 5m / 1h / 24h when hourly series omitted." : "."}
            </p>
            <Sparkline
              values={buckets}
              strokeClassName="stroke-cyan-400"
              fillClassName="fill-cyan-500/15"
              aria-label="Transaction event counts per UTC hour"
            />
          </div>
        </div>
      )}
    </section>
  );
}
