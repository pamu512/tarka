import { useCallback, useEffect, useMemo, useState } from "react";
import { decisions, type EntityTimelineResponse } from "@/api/client";

/**
 * R10 investigation-workspace slice: saved entity sets + cross-entity timeline.
 *
 * Guardrails: this is NOT a case. No assignment, no status, no queue semantics
 * (M2/M7). Sets are a desk-local bookmark of canvas entity ids (localStorage);
 * the timeline is a read-only merge of real decision_audit rows - every row is
 * trace-cited, nothing invented.
 */

const STORAGE_KEY = "tarka.graph.entity_sets";
const MAX_SETS = 20;
const MAX_IDS = 10;

export interface EntitySet {
  name: string;
  entityIds: string[];
  createdAt: string;
}

function loadSets(): EntitySet[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as EntitySet[]) : [];
    return Array.isArray(parsed) ? parsed.filter((s) => s && typeof s.name === "string") : [];
  } catch {
    return [];
  }
}

function persistSets(sets: EntitySet[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sets.slice(0, MAX_SETS)));
}

export function EntitySetPanel({
  tenantId,
  canvasEntityIds,
  onLoadSet,
}: {
  tenantId: string;
  canvasEntityIds: string[];
  onLoadSet: (entityIds: string[]) => void;
}) {
  const [sets, setSets] = useState<EntitySet[]>([]);
  const [nameDraft, setNameDraft] = useState("");
  const [activeSet, setActiveSet] = useState<EntitySet | null>(null);
  const [timeline, setTimeline] = useState<EntityTimelineResponse | null>(null);
  const [timelineErr, setTimelineErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSets(loadSets());
  }, []);

  const saveCurrent = useCallback(() => {
    const name = nameDraft.trim();
    if (!name || canvasEntityIds.length === 0) return;
    const entry: EntitySet = {
      name,
      entityIds: Array.from(new Set(canvasEntityIds)).slice(0, MAX_IDS),
      createdAt: new Date().toISOString(),
    };
    setSets((prev) => {
      const next = [entry, ...prev.filter((s) => s.name !== name)].slice(0, MAX_SETS);
      persistSets(next);
      return next;
    });
    setNameDraft("");
  }, [nameDraft, canvasEntityIds]);

  const removeSet = useCallback((name: string) => {
    setSets((prev) => {
      const next = prev.filter((s) => s.name !== name);
      persistSets(next);
      return next;
    });
    setActiveSet((cur) => (cur?.name === name ? null : cur));
  }, []);

  const openTimeline = useCallback(
    async (set: EntitySet) => {
      setActiveSet(set);
      setTimeline(null);
      setTimelineErr("");
      setBusy(true);
      try {
        const res = await decisions.entityTimeline(tenantId, set.entityIds, 100);
        setTimeline(res);
      } catch {
        setTimelineErr("Timeline unavailable (decision plane).");
      } finally {
        setBusy(false);
      }
    },
    [tenantId],
  );

  const rows = useMemo(() => timeline?.timeline ?? [], [timeline]);

  return (
    <section aria-label="Entity sets" className="rounded-lg border border-white/10 bg-slate-900/60 p-3 space-y-3" data-testid="entity-set-panel">
      <header className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Entity sets</h3>
        <span className="text-[10px] text-gray-500" data-testid="entity-set-note">
          local bookmarks - not cases
        </span>
      </header>

      <div className="flex gap-2">
        <input
          value={nameDraft}
          onChange={(e) => setNameDraft(e.target.value)}
          placeholder={canvasEntityIds.length ? `Save ${Math.min(canvasEntityIds.length, MAX_IDS)} canvas ids as…` : "Load canvas first"}
          disabled={canvasEntityIds.length === 0}
          className="min-w-0 flex-1 rounded border border-white/10 bg-slate-950/60 px-2 py-1 text-xs text-gray-200 placeholder:text-gray-600 focus:border-cyan-500/50 focus:outline-none"
          aria-label="Set name"
          data-testid="entity-set-name"
        />
        <button
          onClick={saveCurrent}
          disabled={!nameDraft.trim() || canvasEntityIds.length === 0}
          className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1 text-xs font-medium text-cyan-300 disabled:opacity-40"
          data-testid="entity-set-save"
        >
          Save
        </button>
      </div>

      {sets.length === 0 && !nameDraft && (
        <p className="text-[11px] text-gray-500">No sets saved yet.</p>
      )}

      <ul className="space-y-1.5" data-testid="entity-set-list">
        {sets.map((s) => (
          <li key={s.name} className="flex items-center gap-2 rounded border border-white/5 bg-slate-950/40 px-2 py-1.5">
            <button
              onClick={() => onLoadSet(s.entityIds)}
              className="min-w-0 flex-1 text-left text-xs text-gray-200 hover:text-cyan-300"
              title={`Load ${s.entityIds.length} ids onto the canvas filter`}
            >
              <span className="font-medium">{s.name}</span>
              <span className="ml-2 text-[10px] text-gray-500">{s.entityIds.length} ids</span>
            </button>
            <button
              onClick={() => openTimeline(s)}
              className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-gray-300 hover:border-cyan-500/40 hover:text-cyan-300"
              data-testid={`entity-set-timeline-${s.name}`}
            >
              Timeline
            </button>
            <button
              onClick={() => removeSet(s.name)}
              className="text-[10px] text-gray-600 hover:text-rose-400"
              aria-label={`Remove set ${s.name}`}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>

      {activeSet && (
        <div className="rounded border border-white/10 bg-slate-950/50 p-2" data-testid="entity-timeline">
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-[11px] font-medium text-gray-300">
              Timeline · {activeSet.name}
            </span>
            {timeline && (
              <span className="text-[10px] text-gray-500" data-testid="entity-timeline-count">
                {timeline.total} rows
              </span>
            )}
          </div>
          {busy && <p className="text-[11px] text-gray-500">Loading…</p>}
          {timelineErr && <p className="text-[11px] text-rose-400" data-testid="entity-timeline-error">{timelineErr}</p>}
          {rows.length > 0 && (
            <ul className="max-h-56 space-y-1 overflow-y-auto pr-1">
              {rows.map((r) => (
                <li key={r.trace_id} className="flex items-center gap-2 text-[11px]">
                  <span className="w-32 shrink-0 truncate font-mono text-gray-400" title={r.entity_id}>{r.entity_id}</span>
                  <span
                    className={
                      r.decision === "DENY"
                        ? "rounded bg-rose-500/15 px-1.5 py-0.5 font-semibold text-rose-300"
                        : r.decision === "REVIEW"
                          ? "rounded bg-amber-500/15 px-1.5 py-0.5 font-semibold text-amber-300"
                          : "rounded bg-emerald-500/15 px-1.5 py-0.5 font-semibold text-emerald-300"
                    }
                  >
                    {r.decision ?? "?"}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-gray-500">{r.created_at ?? ""}</span>
                  <a
                    href={`/cases?trace_id=${encodeURIComponent(r.trace_id)}&tenant_id=${encodeURIComponent(tenantId)}`}
                    className="shrink-0 text-cyan-400 hover:text-cyan-300"
                    title={`Audit trace ${r.trace_id}`}
                  >
                    trace
                  </a>
                </li>
              ))}
            </ul>
          )}
          {!busy && !timelineErr && timeline && rows.length === 0 && (
            <p className="text-[11px] text-gray-500">No decision rows for these entities.</p>
          )}
        </div>
      )}
    </section>
  );
}
