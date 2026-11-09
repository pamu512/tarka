import { ConditionGroupEditor } from "./ConditionGroupEditor";
import { ScoreDeltaEditor } from "./ScoreDeltaEditor";
import { TagRuleEditor } from "./TagRuleEditor";
import type { CatalogFieldDef } from "../registry/catalogToFields";
import { usePackDraftStore } from "../store/packDraftStore";

type Props = {
  fields: CatalogFieldDef[];
};

export function PackFormEditor({ fields }: Props) {
  const draft = usePackDraftStore((s) => s.draft);
  const setCondition = usePackDraftStore((s) => s.setCondition);
  const addCondition = usePackDraftStore((s) => s.addCondition);
  const removeCondition = usePackDraftStore((s) => s.removeCondition);
  const moveCondition = usePackDraftStore((s) => s.moveCondition);
  const setScoreDelta = usePackDraftStore((s) => s.setScoreDelta);
  const setTags = usePackDraftStore((s) => s.setTags);
  const addRule = usePackDraftStore((s) => s.addRule);
  const setPackMeta = usePackDraftStore((s) => s.setPackMeta);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label htmlFor="studio-pack-name" className="block text-xs text-gray-400 mb-1">
            Pack name
          </label>
          <input
            id="studio-pack-name"
            value={draft.name ?? ""}
            onChange={(e) => setPackMeta({ name: e.target.value })}
            className="w-64 bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        {draft.mode && (
          <p className="text-xs text-gray-500">
            Mode: <span className="font-mono text-gray-400">{draft.mode}</span>
          </p>
        )}
      </div>

      {draft.rules.map((rule) => {
        const advanced = rule.rawBlocks.some(
          (b) => b.kind === "both_set_rule" || b.kind === "when_ast",
        );
        return (
          <section
            key={rule.id}
            className="border border-surface-700 rounded-lg p-4 bg-surface-900/40 space-y-3"
            aria-label={`Rule ${rule.id}`}
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-gray-300 font-mono">{rule.id}</h3>
              {advanced && (
                <span className="text-[10px] uppercase tracking-wide bg-amber-900/40 text-amber-300 border border-amber-700/50 rounded px-2 py-0.5">
                  Advanced rule - edit via JSON tab
                </span>
              )}
            </div>
            {advanced ? (
              <p className="text-xs text-gray-500">
                This rule has a deep AST or both when + when_ast set. Form editing is disabled to
                avoid silent flatten.
              </p>
            ) : (
              <>
                <ConditionGroupEditor
                  ruleId={rule.id}
                  conditions={rule.when}
                  fields={fields}
                  onChange={(cid, patch) => setCondition(rule.id, cid, patch)}
                  onAdd={() => addCondition(rule.id)}
                  onRemove={(cid) => removeCondition(rule.id, cid)}
                  onMove={(cid, dir) => moveCondition(rule.id, cid, dir)}
                />
                <ScoreDeltaEditor
                  ruleId={rule.id}
                  value={rule.score_delta ?? 0}
                  onChange={(v) => setScoreDelta(rule.id, v)}
                />
                <TagRuleEditor
                  ruleId={rule.id}
                  tags={rule.tags ?? []}
                  onChange={(t) => setTags(rule.id, t)}
                />
              </>
            )}
          </section>
        );
      })}

      <button
        type="button"
        onClick={addRule}
        className="text-sm text-brand-400 hover:text-brand-300 focus:outline-none focus:ring-1 focus:ring-brand-500 rounded px-2 py-1"
      >
        + Add rule
      </button>
    </div>
  );
}
