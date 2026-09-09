import { useEffect, useState } from "react";

import { decisions } from "../api/client";

export type PackMetricsSlot = {
  pack_id?: string;
  rule_hit_rate: number | null;
  shadow_divergence: number | null;
};

export function packMetricsOneLiner(metrics: PackMetricsSlot | null): string {
  const hit = metrics?.rule_hit_rate ?? null;
  const div = metrics?.shadow_divergence ?? null;
  if (hit == null && div == null) {
    return "Pack metrics are not yet available for this pack. A human still owns Promote.";
  }
  const hitBit = hit == null ? "unknown" : `${Math.round(hit * 100)}%`;
  const divBit = div == null ? "unknown" : `${Math.round(div * 100)}%`;
  return `This pack hit rules on ${hitBit} of Observe rows and diverged on ${divBit}. Thresholds are tenant policy, not Tarka morals.`;
}

function rateLine(label: string, value: number | null): string {
  return value == null ? `${label}: not loaded` : `${label}: ${value}`;
}

function pickPackRow(
  rows: Array<{ pack_id?: string; rule_hit_rate?: number | null; shadow_divergence?: number | null }>,
  packName: string,
  packFile?: string,
): PackMetricsSlot | null {
  const fileStem = (packFile || "").replace(/\.json$/i, "");
  const hit = rows.find((r) => {
    const id = (r.pack_id || "").trim();
    return id === packName || id === packFile || (fileStem && id === fileStem);
  });
  if (!hit) return null;
  return {
    pack_id: hit.pack_id,
    rule_hit_rate: hit.rule_hit_rate ?? null,
    shadow_divergence: hit.shadow_divergence ?? null,
  };
}

export function PromoteConfirmDialog({
  packName,
  packFile,
  tenantId = "demo",
  metrics,
  onCancel,
  onConfirm,
}: {
  packName: string;
  packFile?: string;
  tenantId?: string;
  metrics?: PackMetricsSlot | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [fetched, setFetched] = useState<PackMetricsSlot | null>(metrics ?? null);

  useEffect(() => {
    if (metrics) {
      setFetched(metrics);
      return;
    }
    const tenant = tenantId.trim();
    if (!tenant) {
      setFetched({ rule_hit_rate: null, shadow_divergence: null });
      return;
    }
    let cancelled = false;
    void decisions
      .loopMetrics(tenant)
      .then((out) => {
        if (cancelled) return;
        const row = pickPackRow(out.pack_metrics || [], packName, packFile);
        setFetched(row ?? { pack_id: packName, rule_hit_rate: null, shadow_divergence: null });
      })
      .catch(() => {
        if (!cancelled) setFetched({ pack_id: packName, rule_hit_rate: null, shadow_divergence: null });
      });
    return () => {
      cancelled = true;
    };
  }, [metrics, tenantId, packName, packFile]);

  const hit = fetched?.rule_hit_rate ?? null;
  const div = fetched?.shadow_divergence ?? null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="presentation"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="promote-to-active-title"
        data-testid="promote-to-active-confirm"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl border border-surface-700 bg-surface-900 p-5 shadow-2xl space-y-3"
      >
        <h2 id="promote-to-active-title" className="text-sm font-semibold text-gray-100">
          Promote to Active
        </h2>
        <p className="text-sm text-gray-300">
          <span className="font-medium text-gray-100">{packName}</span>
          {packFile ? <span className="font-mono text-xs text-gray-400"> {packFile}</span> : null}{" "}
          becomes live / Active. A human must confirm. Cancel leaves the pack in Observe.
        </p>
        <div data-testid="promote-pack-metrics" className="rounded-lg border border-surface-700 bg-surface-950/80 px-3 py-2 text-xs text-gray-400 space-y-1">
          <p data-testid="promote-rule-hit-rate">{rateLine("Rule hit rate", hit)}</p>
          <p data-testid="promote-shadow-divergence">{rateLine("Observe divergence", div)}</p>
          <p data-testid="promote-metrics-oneliner">{packMetricsOneLiner(fetched)}</p>
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-surface-600 text-gray-300 hover:border-surface-500"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="promote-to-active-confirm-yes"
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 hover:bg-brand-500 text-white"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
