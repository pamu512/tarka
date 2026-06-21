import { SupportIdHint } from "./SupportIdHint";

export type DegradedModeBannerProps = {
  /** Partial-degradation warnings (amber, non-blocking). */
  warnings?: string[];
  /** Blocking fetch/action error (rose). */
  error?: string | null;
  title?: string;
  hint?: string;
  onDismiss?: () => void;
  onRetry?: () => void;
  className?: string;
};

export function DegradedModeBanner({
  warnings = [],
  error,
  title,
  hint,
  onDismiss,
  onRetry,
  className,
}: DegradedModeBannerProps) {
  const trimmedError = error?.trim() ?? "";
  const activeWarnings = warnings.map((w) => w.trim()).filter(Boolean);

  if (!trimmedError && activeWarnings.length === 0) return null;

  if (trimmedError) {
    return (
      <div
        className={
          className ??
          "rounded-lg border border-rose-500/35 bg-rose-500/10 px-4 py-3 text-sm text-rose-300 space-y-1.5"
        }
        role="alert"
      >
        <div className="flex items-start justify-between gap-3">
          <p className="font-medium">{title ?? "Request failed"}</p>
          {onDismiss ? (
            <button
              type="button"
              onClick={onDismiss}
              className="shrink-0 text-rose-300/80 hover:text-rose-100"
              aria-label="Dismiss error"
            >
              ×
            </button>
          ) : null}
        </div>
        <p>{trimmedError}</p>
        <SupportIdHint
          message={trimmedError}
          className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
          buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
        />
        {hint ? <p className="text-[11px] text-rose-300/80">{hint}</p> : null}
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-1 px-3 py-1.5 rounded-lg bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/30 text-xs text-rose-100"
          >
            Retry
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={
        className ??
        "rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200/90"
      }
      role="status"
    >
      <p className="font-medium">{title ?? "Some panels are degraded."}</p>
      <p className="text-amber-100/80">{activeWarnings.join(" · ")}</p>
      {hint ? <p className="mt-1 text-[11px] text-amber-100/70">{hint}</p> : null}
    </div>
  );
}
