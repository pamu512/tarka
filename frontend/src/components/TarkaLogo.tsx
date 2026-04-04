import { TarkaMark } from "./TarkaMark";

type Variant = "compact" | "full";

/**
 * Brand lockup: vector mark + wordmark. Uses currentColor — black on light surfaces, white on dark (Tailwind `dark:`).
 */
export function TarkaLogo({
  className = "",
  variant = "compact",
}: {
  className?: string;
  variant?: Variant;
}) {
  const theme = "text-gray-950 dark:text-white";

  if (variant === "full") {
    return (
      <div
        className={`flex flex-col items-center text-center gap-1.5 min-w-0 ${theme} ${className}`.trim()}
        role="img"
        aria-label="Tarka — Prove every signal."
      >
        <TarkaMark className="h-[3.25rem] w-[2.6rem] shrink-0" />
        <div className="text-[1.125rem] sm:text-xl font-extrabold tracking-[0.2em] leading-none">TARKA</div>
        <p className="text-[0.65rem] sm:text-xs font-normal tracking-wide opacity-80 max-w-[14rem] leading-snug">
          Prove every signal.
        </p>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2.5 min-w-0 ${theme} ${className}`.trim()}>
      <TarkaMark className="h-9 w-[1.8rem] shrink-0" />
      <span className="text-lg font-semibold tracking-wide truncate">Tarka</span>
    </div>
  );
}
