import type { ReactElement } from "react";

import { isSocialEngineeringFlagged } from "../../utils/socialEngineering";

export type SocialEngineeringFlagProps = {
  isSocialEngineeringFlag?: boolean | null;
  signals?: string[] | null;
  minutesToEmail?: number | null;
  minutesToPassword?: number | null;
  size?: "sm" | "md";
  className?: string;
};

/** UI flag for credential changes after a high-value listing (Prompt 184). */
export function SocialEngineeringFlag({
  isSocialEngineeringFlag,
  signals,
  minutesToEmail,
  minutesToPassword,
  size = "sm",
  className = "",
}: SocialEngineeringFlagProps): ReactElement | null {
  if (!isSocialEngineeringFlagged(isSocialEngineeringFlag, signals)) {
    return null;
  }

  const pad = size === "md" ? "px-2 py-1 text-[10px]" : "px-1.5 py-0.5 text-[9px]";
  const titleParts = [
    "Social engineering pattern",
    minutesToEmail != null ? `email +${minutesToEmail.toFixed(1)}m` : null,
    minutesToPassword != null ? `password +${minutesToPassword.toFixed(1)}m` : null,
  ].filter(Boolean);

  return (
    <span
      title={titleParts.join(" · ")}
      className={`inline-flex items-center gap-1 rounded border border-orange-500/50 bg-orange-950/40 font-semibold uppercase tracking-wide text-orange-200 ${pad} ${className}`}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-orange-400" aria-hidden />
      Soc eng
    </span>
  );
}
