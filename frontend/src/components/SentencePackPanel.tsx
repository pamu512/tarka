import { useMemo, useState } from "react";

import { rules } from "../api/client";
import { toUserFacingError } from "../utils/userFacingErrors";
import {
  HOP_ETYPES,
  VELOCITY_KEYS,
  emitHopPack,
  emitVelocityPack,
  type HopSentence,
  type VelocitySentence,
} from "../utils/sentencePack";

export function SentencePackPanel({ onJson }: { onJson: (text: string) => void }) {
  const [field, setField] = useState<VelocitySentence["field"]>("event_count_1h");
  const [op, setOp] = useState<VelocitySentence["op"]>("gte");
  const [value, setValue] = useState(20);
  const [etype, setEtype] = useState<HopSentence["etype"]>("USES_DEVICE");
  const [kind, setKind] = useState<"velocity" | "hop">("velocity");

  const [edited, setEdited] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState("");
  const [saving, setSaving] = useState(false);

  const json = useMemo(() => {
    const pack =
      kind === "velocity"
        ? emitVelocityPack({ field, op, value })
        : emitHopPack({ etype });
    return JSON.stringify(pack, null, 2);
  }, [kind, field, op, value, etype]);

  const shown = edited ?? json;

  return (
    <section
      data-testid="sentence-pack-panel"
      className="mx-6 mt-3 rounded-md border border-surface-700 bg-surface-900/60 px-3 py-2 text-sm text-gray-300"
    >
      <p className="text-xs text-gray-500 mb-2">
        Sentence → same Observe JSON evaluate already runs. You can edit the JSON. Promote is not here.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value === "hop" ? "hop" : "velocity")}
          className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
        >
          <option value="velocity">When a count or sum crosses a threshold</option>
          <option value="hop">FLAG when this person shares an edge</option>
        </select>
        {kind === "velocity" ? (
          <>
            <select
              value={field}
              onChange={(e) => setField(e.target.value as VelocitySentence["field"])}
              className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
            >
              {VELOCITY_KEYS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <select
              value={op}
              onChange={(e) => setOp(e.target.value as VelocitySentence["op"])}
              className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
            >
              <option value="gte">≥</option>
              <option value="gt">&gt;</option>
              <option value="lte">≤</option>
              <option value="lt">&lt;</option>
            </select>
            <input
              type="number"
              value={value}
              onChange={(e) => setValue(Number(e.target.value))}
              className="w-24 bg-surface-800 border border-surface-600 rounded px-2 py-1"
            />
          </>
        ) : (
          <select
            value={etype}
            onChange={(e) => setEtype(e.target.value as HopSentence["etype"])}
            className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
          >
            {HOP_ETYPES.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          onClick={() => {
            setEdited(null);
            onJson(json);
          }}
          className="px-2 py-1 rounded bg-surface-700 text-gray-200 hover:bg-surface-600"
        >
          Reset JSON
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            void (async () => {
              setSaving(true);
              setSaveMsg("");
              try {
                const pack = JSON.parse(shown) as { name?: string; rules?: unknown[] };
                const name = String(pack.name || "").trim();
                const packRules = Array.isArray(pack.rules) ? pack.rules : [];
                if (!name || !packRules.length) {
                  setSaveMsg("Invalid pack JSON — not saved.");
                  return;
                }
                await rules.create({ name, rules: packRules, tag_rules: [] });
                onJson(shown);
                setSaveMsg("Saved as Observe draft. Promote is not here.");
              } catch (e) {
                setSaveMsg(
                  e instanceof SyntaxError
                    ? "Invalid pack JSON — not saved."
                    : toUserFacingError(e, { subject: "Observe pack", action: "save sentence pack" }),
                );
              } finally {
                setSaving(false);
              }
            })();
          }}
          className="px-2 py-1 rounded bg-brand-700 text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save as Observe"}
        </button>
        {saveMsg ? <span className="text-xs text-gray-400">{saveMsg}</span> : null}
      </div>
      <textarea
        value={shown}
        onChange={(e) => setEdited(e.target.value)}
        className="mt-2 w-full max-h-40 min-h-[8rem] bg-surface-950 text-[11px] text-gray-400 font-mono"
        spellCheck={false}
      />
    </section>
  );
}
