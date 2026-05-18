import type { Case } from "../api/client";

/** Prefer API field; otherwise infer from title/labels for queue analytics. */
export function resolveCaseType(c: Case): string {
  const raw = c.case_type;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  const t = c.title.toLowerCase();
  if (/\bato\b/.test(t) || t.includes("account takeover")) return "Account takeover";
  if (t.includes("chargeback") || t.includes("dispute")) return "Dispute / chargeback";
  if (t.includes("velocity")) return "Velocity / payments";
  if (t.includes("scam")) return "Scam / social engineering";
  if (c.labels?.length) {
    const first = c.labels[0];
    if (first) return first.charAt(0).toUpperCase() + first.slice(1);
  }
  return "General";
}

export function teamLabel(c: Case): string {
  const t = c.assigned_team?.trim();
  return t || "Unassigned";
}

export function isTerminalStatus(s: Case["status"]): boolean {
  return s === "resolved" || s === "closed";
}

/** Wall-clock hours from creation to last update for terminal cases. */
export function hoursToResolve(c: Case): number | null {
  if (!isTerminalStatus(c.status)) return null;
  const a = new Date(c.created_at).getTime();
  const b = new Date(c.updated_at).getTime();
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null;
  return (b - a) / 3600000;
}

function medianSorted(sorted: number[]): number | null {
  if (sorted.length === 0) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

function percentileSorted(sorted: number[], p: number): number | null {
  if (sorted.length === 0) return null;
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo]!;
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (idx - lo);
}

export type WorkloadTeamTypeRow = {
  team: string;
  caseType: string;
  resolvedCount: number;
  openCount: number;
  medianHours: number | null;
  p90Hours: number | null;
  avgHours: number | null;
};

export function buildTeamTypeWorkloadRows(cases: Case[]): WorkloadTeamTypeRow[] {
  const map = new Map<string, { hours: number[]; open: number; resolved: number }>();
  for (const c of cases) {
    const key = `${teamLabel(c)}|${resolveCaseType(c)}`;
    let e = map.get(key);
    if (!e) {
      e = { hours: [], open: 0, resolved: 0 };
      map.set(key, e);
    }
    if (isTerminalStatus(c.status)) {
      e.resolved += 1;
      const h = hoursToResolve(c);
      if (h != null) e.hours.push(h);
    } else {
      e.open += 1;
    }
  }
  const rows: WorkloadTeamTypeRow[] = [];
  for (const [key, e] of map) {
    const pipe = key.indexOf("|");
    const team = pipe >= 0 ? key.slice(0, pipe) : key;
    const caseType = pipe >= 0 ? key.slice(pipe + 1) : "General";
    const sorted = [...e.hours].sort((a, b) => a - b);
    rows.push({
      team,
      caseType,
      resolvedCount: e.resolved,
      openCount: e.open,
      medianHours: medianSorted(sorted),
      p90Hours: percentileSorted(sorted, 90),
      avgHours: sorted.length ? sorted.reduce((a, b) => a + b, 0) / sorted.length : null,
    });
  }
  rows.sort((a, b) => a.team.localeCompare(b.team) || a.caseType.localeCompare(b.caseType));
  return rows;
}

export type CaseTypeTtrSummary = {
  caseType: string;
  resolvedCount: number;
  medianHours: number | null;
  p90Hours: number | null;
  avgHours: number | null;
};

export function summarizeTimeToResolveByCaseType(cases: Case[]): CaseTypeTtrSummary[] {
  const by = new Map<string, number[]>();
  for (const c of cases) {
    if (!isTerminalStatus(c.status)) continue;
    const h = hoursToResolve(c);
    if (h == null) continue;
    const ct = resolveCaseType(c);
    const arr = by.get(ct) ?? [];
    arr.push(h);
    by.set(ct, arr);
  }
  const out: CaseTypeTtrSummary[] = [];
  for (const [caseType, hours] of by) {
    const sorted = [...hours].sort((a, b) => a - b);
    out.push({
      caseType,
      resolvedCount: sorted.length,
      medianHours: medianSorted(sorted),
      p90Hours: percentileSorted(sorted, 90),
      avgHours: sorted.length ? sorted.reduce((a, b) => a + b, 0) / sorted.length : null,
    });
  }
  out.sort((a, b) => b.resolvedCount - a.resolvedCount || a.caseType.localeCompare(b.caseType));
  return out;
}

export function formatHoursDuration(h: number | null): string {
  if (h == null || !Number.isFinite(h)) return "—";
  if (h < 24) return `${h.toFixed(1)} h`;
  const d = Math.floor(h / 24);
  const rem = h - d * 24;
  return `${d}d ${rem < 1 ? rem.toFixed(1) : Math.round(rem)}h`;
}
