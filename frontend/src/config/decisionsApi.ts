/** Browser base path for decision-api when proxied through Vite (core mounts at `/decisions`). */
export function decisionsApiBase(): string {
  const raw = (import.meta.env.VITE_DECISIONS_API_BASE as string | undefined)?.trim();
  return raw || "/api/decisions";
}
