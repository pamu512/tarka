import {
  DELIVERY_RELIABILITY_HELP,
  type DeliveryStatusView,
} from "../../utils/deliveryStatus";

const CHIP_CLS: Record<DeliveryStatusView["chip"], string> = {
  emitted: "bg-sky-500/15 text-sky-200 border-sky-500/35",
  acked: "bg-emerald-500/15 text-emerald-200 border-emerald-500/35",
  retrying: "bg-amber-500/15 text-amber-200 border-amber-500/35",
  dead_lettered: "bg-orange-500/15 text-orange-200 border-orange-500/35",
  failed: "bg-rose-500/15 text-rose-200 border-rose-500/35",
  not_configured: "bg-surface-800 text-gray-300 border-surface-600",
};

export function DeliveryStatusStrip({ view }: { view: DeliveryStatusView }) {
  return (
    <section
      data-testid="delivery-status-strip"
      aria-label="Enforcement delivery status"
      className="border-b border-surface-700 bg-surface-950/90 px-4 py-2.5"
    >
      <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500">Delivery</p>
      <span
        data-testid="delivery-status-chip"
        data-status={view.chip}
        className={`mt-1.5 inline-flex rounded-md border px-1.5 py-0.5 text-[11px] font-semibold ${CHIP_CLS[view.chip]}`}
      >
        {view.label}
      </span>
      <p data-testid="delivery-status-hint" className="mt-1.5 text-xs text-gray-400 leading-snug">
        {view.hint}
      </p>
      <p data-testid="delivery-status-help" className="mt-1 text-[11px] text-gray-500 leading-snug">
        {DELIVERY_RELIABILITY_HELP}
      </p>
    </section>
  );
}
