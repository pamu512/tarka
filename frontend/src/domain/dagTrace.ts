/**
 * Normalization + heuristics for decision evaluate ``step_trace`` rows (audit ``payload_snapshot``).
 */

export type StepTraceRow = {
  index: number;
  step: string;
  status: string;
  attempts?: number;
  duration_ms?: number;
  reason?: string | null;
  /** Original row for raw JSON / debugging */
  raw: Record<string, unknown>;
};

export type ParsedStepTrace = {
  rows: StepTraceRow[];
  warnings: string[];
};

function asRecord(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) return v as Record<string, unknown>;
  return null;
}

/**
 * Coerce server ``step_trace`` into a flat list of rows; never throws.
 * Collects human-readable warnings when the payload is incomplete or malformed.
 */
export function parseStepTrace(input: unknown): ParsedStepTrace {
  const warnings: string[] = [];
  if (input === undefined || input === null) {
    warnings.push("Trace missing: no step_trace field in this audit payload.");
    return { rows: [], warnings };
  }
  if (!Array.isArray(input)) {
    warnings.push("step_trace is not a JSON array — cannot render the execution DAG.");
    return { rows: [], warnings };
  }
  const rows: StepTraceRow[] = [];
  input.forEach((item, i) => {
    const o = asRecord(item);
    if (!o) {
      warnings.push(`Entry ${i} is not an object — skipped.`);
      return;
    }
    const step = typeof o.step === "string" && o.step.trim() ? o.step.trim() : `unknown_step_${i}`;
    const status = typeof o.status === "string" && o.status.trim() ? o.status.trim().toLowerCase() : "unknown";
    const attempts = typeof o.attempts === "number" && Number.isFinite(o.attempts) ? o.attempts : undefined;
    const duration_ms = typeof o.duration_ms === "number" && Number.isFinite(o.duration_ms) ? o.duration_ms : undefined;
    const reason =
      typeof o.reason === "string"
        ? o.reason
        : o.reason === null || o.reason === undefined
          ? null
          : String(o.reason);
    rows.push({ index: rows.length, step, status, attempts, duration_ms, reason, raw: o });
  });
  if (input.length > 0 && rows.length === 0) {
    warnings.push("step_trace had entries but none could be parsed as objects.");
  }
  return { rows, warnings };
}

function severityForHighlight(r: StepTraceRow): number {
  if (r.status === "failed") return 4;
  if (r.status === "skipped" && r.reason && /reject|integrity|replay|blacklist|force|sanction|deny|blocked|routing/i.test(r.reason)) {
    return 3;
  }
  if (r.status === "skipped" && r.reason && /timeout|http_error|error:/i.test(r.reason)) return 2;
  if (r.status === "skipped") return 1;
  if (r.status === "unknown") return 1;
  return 0;
}

/**
 * Pick the row most likely responsible for a degraded / blocked outcome.
 * Falls back to the last non-ok row when decision is deny/review and severities tie at zero.
 */
export function findFailureHighlightIndex(rows: StepTraceRow[], decision: string): number | null {
  if (rows.length === 0) return null;
  let bestIdx: number | null = null;
  let bestScore = -1;
  rows.forEach((r, i) => {
    const s = severityForHighlight(r);
    if (s > bestScore) {
      bestScore = s;
      bestIdx = i;
    }
  });
  if (bestScore > 0 && bestIdx !== null) return bestIdx;
  if (/deny|review/i.test(decision)) {
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i].status !== "ok") return i;
    }
  }
  return null;
}
