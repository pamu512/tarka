import { validatePackJson } from "../compiler/validatePack";
import { compilePack } from "../compiler/compilePack";
import { usePackDraftStore } from "../store/packDraftStore";

export function ValidatePanel() {
  const draft = usePackDraftStore((s) => s.draft);
  const result = validatePackJson(compilePack(draft));

  const bothSetErrors = draft.rules
    .filter((r) => r.rawBlocks.some((b) => b.kind === "both_set_rule"))
    .map(
      (r) =>
        `Rule ${r.id}: can never fire (when and when_ast both set) - resolve in JSON tab`,
    );

  const errors = [...(result.ok ? [] : result.errors), ...bothSetErrors];

  if (errors.length === 0) {
    return (
      <div className="text-xs text-emerald-400/90 border border-emerald-800/40 rounded px-3 py-2">
        Pack validates.
      </div>
    );
  }

  return (
    <div
      role="alert"
      className="text-xs text-amber-300 border border-amber-700/50 rounded px-3 py-2 space-y-1"
    >
      <div className="font-medium">Validation</div>
      <ul className="list-disc pl-4 space-y-0.5">
        {errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  );
}
