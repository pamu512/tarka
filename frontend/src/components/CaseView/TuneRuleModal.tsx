import { useEffect, useState } from "react";
import type { Edge, Node } from "@xyflow/react";
import { Link } from "react-router-dom";
import { rules, shadow, type RulePack } from "../../api/client";
import { packRuleRecordToFlow } from "../RuleBuilder/jsonAstToReactFlow";
import { RuleBuilderCanvas } from "../RuleBuilder/RuleBuilderCanvas";

function packFile(p: RulePack): string {
  return p._file ?? ((p as unknown as Record<string, unknown>).file as string | undefined) ?? p.name;
}

export function TuneRuleModal({
  open,
  onClose,
  ruleHits,
}: {
  open: boolean;
  onClose: () => void;
  ruleHits: string[];
}) {
  const [selectedHit, setSelectedHit] = useState(ruleHits[0] ?? "");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [graph, setGraph] = useState<{ nodes: Node[]; edges: Edge[] } | null>(null);
  const [persist, setPersist] = useState<{ packFile: string; ruleId: string } | null>(null);
  const [resetKey, setResetKey] = useState(0);

  useEffect(() => {
    if (open && ruleHits.length > 0) {
      setSelectedHit(ruleHits[0]);
    }
  }, [open, ruleHits]);

  useEffect(() => {
    if (!open || !selectedHit) {
      setGraph(null);
      setPersist(null);
      setErr(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      setGraph(null);
      setPersist(null);
      try {
        const listRes = await rules.list();
        const packs = listRes.packs ?? [];
        let filename: string | null = null;
        for (const p of packs) {
          const ruleRows = p.rules ?? [];
          if (ruleRows.some((r) => r.id === selectedHit)) {
            filename = packFile(p);
            break;
          }
        }
        if (!filename) {
          setErr(`Rule "${selectedHit}" was not found in any loaded rule pack.`);
          return;
        }
        const full = await shadow.getPack(filename);
        const rawRule = (full.rules ?? []).find((r) => (r as { id?: string }).id === selectedHit);
        if (!rawRule) {
          setErr(`Rule "${selectedHit}" is missing from pack file ${filename}.`);
          return;
        }
        const flow = packRuleRecordToFlow(rawRule as unknown as Record<string, unknown>);
        if (cancelled) return;
        setGraph(flow);
        setPersist({ packFile: filename, ruleId: selectedHit });
        setResetKey((k) => k + 1);
      } catch (e) {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, selectedHit]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tune-rule-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-6xl max-h-[92vh] overflow-y-auto rounded-xl border border-surface-600 bg-surface-950 shadow-xl">
        <header className="sticky top-0 z-10 flex flex-wrap items-start justify-between gap-3 border-b border-surface-700 bg-surface-950/95 px-4 py-3 backdrop-blur">
          <div>
            <h2 id="tune-rule-title" className="text-lg font-semibold text-gray-100">
              Tune rule
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              Rule builder pre-loaded from the fired rule. Save updates the pack on the decision API (governance secret may be
              required).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {ruleHits.length > 1 ? (
              <label className="text-xs text-gray-500 flex flex-col gap-1">
                Fired rule
                <select
                  value={selectedHit}
                  onChange={(e) => setSelectedHit(e.target.value)}
                  className="bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-sm text-gray-200 max-w-[min(100%,18rem)]"
                >
                  {ruleHits.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <Link to="/rules/visual" className="text-xs font-medium text-brand-400 hover:text-brand-300 px-2 py-1.5 rounded-lg">
              Full-page builder
            </Link>
            <button
              type="button"
              className="text-xs font-medium text-gray-400 hover:text-gray-200 px-3 py-1.5 rounded-lg border border-surface-600 hover:bg-surface-800"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </header>
        <div className="p-4">
          {err ? (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300 mb-4">{err}</div>
          ) : null}
          {loading ? (
            <div className="flex justify-center py-16">
              <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : graph && persist ? (
            <RuleBuilderCanvas
              resetKey={resetKey}
              initialGraph={graph}
              variant="modal"
              persistTarget={persist}
            />
          ) : !err && ruleHits.length === 0 ? (
            <p className="text-sm text-gray-500 py-8 text-center">No rule hits on this audit — nothing to tune.</p>
          ) : !err ? (
            <p className="text-sm text-gray-500 py-8 text-center">Could not load the rule graph.</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
