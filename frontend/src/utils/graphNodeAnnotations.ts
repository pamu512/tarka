/**
 * Browser-local annotation layer for graph nodes (case-scoped).
 * Surfaces notes such as "Known good reseller account" without a dedicated graph API yet.
 */

const STORAGE_PREFIX = "tarka.graphAnnotations.v1";

export function graphAnnotationsStorageKey(tenantId: string, caseId: string): string {
  return `${STORAGE_PREFIX}:${tenantId}:${caseId}`;
}

const MAX_NOTE_LEN = 2000;

export function loadGraphAnnotations(tenantId: string, caseId: string): Record<string, string> {
  if (typeof localStorage === "undefined") return {};
  try {
    const raw = localStorage.getItem(graphAnnotationsStorageKey(tenantId, caseId));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === "string" && v.trim()) {
        out[k] = v.trim().slice(0, MAX_NOTE_LEN);
      }
    }
    return out;
  } catch {
    return {};
  }
}

function persist(tenantId: string, caseId: string, data: Record<string, string>): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(graphAnnotationsStorageKey(tenantId, caseId), JSON.stringify(data));
  } catch {
    /* quota / private mode */
  }
}

export function setGraphNodeAnnotation(
  tenantId: string,
  caseId: string,
  nodeId: string,
  text: string | null,
): Record<string, string> {
  const next = { ...loadGraphAnnotations(tenantId, caseId) };
  const t = (text ?? "").trim().slice(0, MAX_NOTE_LEN);
  if (!t) {
    delete next[nodeId];
  } else {
    next[nodeId] = t;
  }
  persist(tenantId, caseId, next);
  return next;
}
