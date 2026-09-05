export type DeskProfile = "demo" | "product" | "brochure";

export function resolveDeskProfile(env?: { profile?: string; leanNav?: string }): DeskProfile {
  const raw = (env?.profile ?? (import.meta.env.VITE_DESK_PROFILE as string | undefined) ?? "")
    .trim()
    .toLowerCase();
  if (raw === "demo" || raw === "product" || raw === "brochure") return raw;
  const lean = (env?.leanNav ?? (import.meta.env.VITE_LEAN_NAV as string | undefined) ?? "true")
    .trim()
    .toLowerCase();
  return lean === "false" ? "brochure" : "demo";
}
