const STORAGE_KEY = "tarka.sar_approver_actor_id";

export function readSarApproverActorId(): string | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)?.trim();
    return v ? v : null;
  } catch {
    return null;
  }
}

export function persistSarApproverActorId(id: string): void {
  try {
    const t = id.trim();
    if (t) localStorage.setItem(STORAGE_KEY, t);
  } catch {
    /* ignore quota / private mode */
  }
}
