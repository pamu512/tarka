import { useEffect, useState } from "react";
import { Link } from "react-router";

import { decisions, rules } from "../api/client";
import { toUserFacingError } from "../utils/userFacingErrors";

type Draft = { name?: string; file?: string; is_ai_authored?: boolean };
type SlipRow = { rule_id?: string; hypothesis?: string; parked_draft?: string | null; triggers?: string[] };

export function ObserveEasePanel({
  tenantId,
  drafts,
  promoteAllowed,
  blockers,
  slipRules,
  selectedDraft,
  onSelectDraft,
  onPromote,
  canPromote,
}: {
  tenantId: string;
  drafts: Draft[];
  promoteAllowed: boolean;
  blockers: string[];
  slipRules: SlipRow[];
  selectedDraft: string;
  onSelectDraft: (name: string) => void;
  onPromote: () => void;
  canPromote: boolean;
}) {
  const [llm, setLlm] = useState<{ connected: boolean; backend: string; model: string; hint?: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshLlm() {
    try {
      setLlm(await decisions.byomStatus());
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "LLM", action: "read connect status" }));
    }
  }

  useEffect(() => {
    void refreshLlm();
    // ponytail: status is env-backed; one read on mount is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function testLlm() {
    setBusy(true);
    setMsg("");
    try {
      const out = await decisions.byomTest();
      setLlm(out);
      setMsg(out.ok ? "LLM ping ok." : `LLM ${out.hint || "off"}.`);
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "LLM", action: "ping the configured URL" }));
    } finally {
      setBusy(false);
    }
  }

  async function draftObserve() {
    setBusy(true);
    setMsg("");
    try {
      await rules.createScoutPack({
        name: `desk_scout_${Date.now()}`,
        tenant_id: tenantId,
        rules: [
          {
            id: "desk_scout_event_count_1h",
            when: [{ field: "event_count_1h", op: "gte", value: 40 }],
            score_delta: 15,
            description: "Desk scout draft",
          },
        ],
      });
      setMsg("Observe draft posted. A model cannot Promote it.");
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "Observe draft", action: "create scout pack" }));
    } finally {
      setBusy(false);
    }
  }

  async function demoteSelected() {
    const file = drafts.find((d) => (d.name || "").trim() === selectedDraft)?.file;
    if (!file) return;
    setBusy(true);
    setMsg("");
    try {
      await rules.setPackMode(file, "shadow");
      setMsg("Human PUT set that pack to Observe. A model did not turn live off.");
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "Observe", action: "set pack mode to shadow" }));
    } finally {
      setBusy(false);
    }
  }

  const ready = promoteAllowed;
  const parked = slipRules.filter((r) => r.parked_draft);
  const pings = slipRules.filter((r) => !r.parked_draft);

  return (
    <section data-testid="observe-ease-panel" className="grid gap-3 md:grid-cols-3">
      <div className="rounded-md border border-surface-700 bg-surface-900/70 px-3 py-2 text-sm md:col-span-3 flex flex-wrap items-center gap-2">
        <span className={llm?.connected ? "text-emerald-300" : "text-gray-400"}>
          LLM {llm?.connected ? "connected" : "off"}
          {llm?.connected && llm.model ? ` · ${llm.model}` : ""}
        </span>
        <button type="button" disabled={busy} onClick={() => void testLlm()} className="px-2 py-1 rounded bg-surface-700 text-gray-200">
          Test
        </button>
        <button type="button" disabled={busy} onClick={() => void draftObserve()} className="px-2 py-1 rounded bg-surface-700 text-gray-200">
          Draft Observe pack
        </button>
        {msg ? <span className="text-xs text-gray-400">{msg}</span> : null}
      </div>
      <article className="rounded-md border border-surface-700 px-3 py-2 text-sm">
        <h3 className="font-semibold text-gray-100">Ready to Promote</h3>
        <p className="text-gray-400 mt-1">
          {ready
            ? "This Observe draft passed the desk gates. A human can Promote it."
            : "No draft is ready. Live packs still decide."}
        </p>
        {ready ? (
          <button type="button" disabled={!canPromote || busy} onClick={onPromote} className="mt-2 px-2 py-1 rounded bg-brand-700 text-white disabled:opacity-50">
            Promote
          </button>
        ) : null}
      </article>
      <article className="rounded-md border border-surface-700 px-3 py-2 text-sm">
        <h3 className="font-semibold text-gray-100">Not yet</h3>
        <p className="text-gray-400 mt-1">{blockers.length ? blockers.join("; ") : "No blockers on the last scan."}</p>
        <ul className="mt-2 text-xs text-gray-500 space-y-1">
          {drafts.map((d) => (
            <li key={d.name}>
              <button type="button" className="text-brand-300 hover:underline" onClick={() => onSelectDraft(d.name || "")}>
                {d.name}
              </button>
              {d.is_ai_authored ? " · model drafted — you own live" : ""}
            </li>
          ))}
        </ul>
      </article>
      <article className="rounded-md border border-surface-700 px-3 py-2 text-sm">
        <h3 className="font-semibold text-gray-100">Live rule slipped</h3>
        <p className="text-gray-400 mt-1">The model did not turn live off.</p>
        {parked.map((r) => (
          <p key={r.rule_id} className="mt-1 text-gray-300">
            {r.hypothesis === "retire"
              ? `Consider taking live rule ${r.rule_id} back to Observe.`
              : `Consider this successor in Observe for ${r.rule_id}.`}{" "}
            <button type="button" className="text-brand-300 hover:underline" onClick={() => onSelectDraft(r.parked_draft || "")}>
              open draft
            </button>
          </p>
        ))}
        {pings.map((r) => (
          <p key={r.rule_id} className="mt-1 text-gray-400">
            {r.rule_id} slipped (ping only).
          </p>
        ))}
        <div className="mt-2 flex gap-2">
          <button type="button" disabled={!canPromote || busy} onClick={onPromote} className="px-2 py-1 rounded bg-surface-700 text-gray-200 disabled:opacity-50">
            Promote draft
          </button>
          <button type="button" disabled={!selectedDraft || busy} onClick={() => void demoteSelected()} className="px-2 py-1 rounded bg-surface-700 text-gray-200 disabled:opacity-50">
            Human demote (PUT)
          </button>
          <Link to="/rules" className="px-2 py-1 text-brand-300 hover:underline">
            Open packs
          </Link>
        </div>
      </article>
    </section>
  );
}
