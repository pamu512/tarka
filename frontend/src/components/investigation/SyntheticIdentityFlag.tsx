import type { ReactElement } from "react";

import { isSyntheticIdentityFlagged, SYNTHETIC_IDENTITY_FLAG_SCORE } from "../../utils/syntheticIdentity";

export type SyntheticIdentityFlagProps = {
  riskScore?: number | null;
  isSyntheticIdentity?: boolean | null;
  /** Show score in tooltip title when compact. */
  comboFlags?: string[] | null;
  size?: "sm" | "md";
  className?: string;
};

/**
 * UI flag for users with high-risk IP / browser / email combinations (Prompt 181).
 */
export function SyntheticIdentityFlag({
  riskScore,
  isSyntheticIdentity,
  comboFlags,
  size = "sm",
  className = "",
}: SyntheticIdentityFlagProps): ReactElement | null {
  if (!isSyntheticIdentityFlagged(riskScore, isSyntheticIdentity)) {
    return null;
  }

  const pad = size === "md" ? "px-2 py-1 text-[10px]" : "px-1.5 py-0.5 text-[9px]";
  const titleParts = [
    `Synthetic identity risk ≥ ${SYNTHETIC_IDENTITY_FLAG_SCORE}`,
    typeof riskScore === "number" ? `score ${riskScore}` : null,
    comboFlags?.length ? comboFlags.join(", ") : null,
  ].filter(Boolean);

  return (
    <span
      title={titleParts.join(" · ")}
      className={`inline-flex items-center gap-1 rounded border border-fuchsia-500/50 bg-fuchsia-950/40 font-semibold uppercase tracking-wide text-fuchsia-200 ${pad} ${className}`}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-fuchsia-400 animate-pulse" aria-hidden />
      Syn ID
    </span>
  );
}
