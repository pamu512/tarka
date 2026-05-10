"use client";

type HealthCardProps = {
  title: string;
  online: boolean;
  latencyMs: number | null;
  errorMessage: string | null;
};

export function HealthCard({ title, online, latencyMs, errorMessage }: HealthCardProps) {
  const stateLabel = online ? "Online" : "Offline";
  const latencyLabel =
    latencyMs !== null && Number.isFinite(latencyMs) ? `${latencyMs} ms` : "—";

  return (
    <article
      className={[
        "flex flex-col rounded-lg border p-4 transition-colors duration-200",
        online
          ? "border-slate-800 bg-slate-900/35"
          : "border-red-800/90 bg-red-950/35 ring-1 ring-red-900/60",
      ].join(" ")}
      aria-label={`${title} health`}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
        <span
          className={[
            "shrink-0 rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
            online
              ? "bg-emerald-950/90 text-emerald-300 ring-1 ring-emerald-800/70"
              : "bg-red-950/90 text-red-200 ring-1 ring-red-800/80",
          ].join(" ")}
        >
          {stateLabel}
        </span>
      </div>
      <dl className="mt-4 space-y-1 text-xs">
        <div className="flex justify-between gap-2 text-slate-400">
          <dt>Latency</dt>
          <dd className="font-mono tabular-nums text-slate-200">{latencyLabel}</dd>
        </div>
      </dl>
      {!online && errorMessage ? (
        <p
          className="mt-3 border-t border-red-900/50 pt-3 text-[11px] leading-snug text-red-200/95"
          role="alert"
        >
          {errorMessage}
        </p>
      ) : null}
    </article>
  );
}
