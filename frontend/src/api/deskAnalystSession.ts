/**
 * Local-desk analyst session: seed API key in sessionStorage only.
 * Never read VITE_API_KEY / API_KEYS from the bundle.
 */

const STORAGE_KEY = "tarka.desk_analyst_api_key";

export function getDeskAnalystApiKey(): string | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    const v = sessionStorage.getItem(STORAGE_KEY)?.trim() ?? "";
    return v || null;
  } catch {
    return null;
  }
}

export function setDeskAnalystApiKey(key: string): void {
  const trimmed = key.trim();
  if (!trimmed) {
    clearDeskAnalystApiKey();
    return;
  }
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, trimmed);
  } catch {
    /* private-mode / quota */
  }
}

export function clearDeskAnalystApiKey(): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function hasDeskAnalystSession(): boolean {
  return Boolean(getDeskAnalystApiKey());
}
