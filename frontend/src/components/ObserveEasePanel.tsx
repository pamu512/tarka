import { useEffect, useState } from "react";
import { Link } from "react-router";

import { decisions, rules } from "../api/client";
import { PromoteConfirmDialog } from "./PromoteConfirmDialog";
import { SentencePackPanel } from "./SentencePackPanel";
import { toUserFacingError } from "../utils/userFacingErrors";

type Draft = { name?: string; file?: string; is_ai_authored?: boolean };
type SlipRow = { rule_id?: string; hypothesis?: string; parked_draft?: string | null; triggers?: string[] };
type LivePack = {
  _file?: string;
  name?: string;
  mode?: string;
  lifecycle?: { demote?: { state?: string; proposed_by?: string } };
};

export function ObserveEasePanel({
  tenantId,
  drafts,
  promoteAllowed,
  blockers,
  slipRules,
  selectedDraft: _selectedDraft,
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
  const [livePacks, setLivePacks] = useState<LivePack[]>([]);
  const [selectedLive, setSelectedLive] = useState("");
  const [demoteReason, setDemoteReason] = useState("");
  const [promoteOpen, setPromoteOpen] = useState(false);

  async function refreshLlm() {
    try {
      setLlm(await decisions.byomStatus());
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "LLM", action: "read connect status" }));
    }
  }

  async function refreshLivePacks() {
    try {
      const out = await rules.list();
      const live = ((out.packs || []) as LivePack[]).filter((p) => {
        const mode = (p.mode || "active").trim();
        return mode === "active" || mode === "";
      });
      setLivePacks(live);
      setSelectedLive((cur) => {
        if (cur && live.some((p) => (p._file || "") === cur)) return cur;
        return live[0]?._file || "";
      });
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "Live packs", action: "list active packs" }));
    }
  }

  useEffect(() => {
    void refreshLlm();
    void refreshLivePacks();
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

  const selectedLivePack = livePacks.find((p) => (p._file || "") === selectedLive);
  const demoteProposed = (selectedLivePack?.lifecycle?.demote?.state || "") === "proposed";
  const reasonReady = demoteReason.trim().length >= 8;
  const selectedDraftPack = drafts.find((d) => (d.name || "") === _selectedDraft) || drafts[0];
  const promoteName = selectedDraftPack?.name || _selectedDraft || "Observe draft";
  const promoteFile = selectedDraftPack?.file;

  async function proposeDemoteSelected() {
    if (!selectedLive || !reasonReady) return;
    setBusy(true);
    setMsg("");
    try {
      await rules.proposeDemote(selectedLive, demoteReason.trim(), tenantId);
      setMsg("Proposed demote. Live is still on. Confirm is a separate human action.");
      await refreshLivePacks();
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "Propose Demote", action: "park a human demote" }));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDemoteSelected() {
    if (!selectedLive || !reasonReady || !demoteProposed) return;
    setBusy(true);
    setMsg("");
    try {
      await rules.confirmDemote(selectedLive, demoteReason.trim());
      setMsg("Confirmed demote. Pack is Observe. A model did not turn live off.");
      await refreshLivePacks();
    } catch (e) {
      setMsg(toUserFacingError(e, { subject: "Confirm demote", action: "flip the proposed pack to Observe" }));
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
      <div className="md:col-span-3" data-testid="observe-sentence-pack">
        <SentencePackPanel onJson={() => undefined} />
      </div>
      <article className="rounded-md border border-surface-700 px-3 py-2 text-sm" data-testid="ready-to-promote" aria-labelledby="ready-to-promote-heading">
        <h3 id="ready-to-promote-heading" className="font-semibold text-gray-100">Ready to Promote</h3>
        <p className="text-gray-400 mt-1">
          {ready
            ? "This Observe draft passed the desk gates. A human can Promote it."
            : drafts.length
              ? "Observe drafts wait here. Live packs still decide until a human Promotes."
              : "No draft is ready. Live packs still decide."}
        </p>
        <p className="text-xs text-gray-500 mt-1">{blockers.length ? blockers.join("; ") : "No blockers on the last scan."}</p>
        <ul className="mt-2 text-xs text-gray-500 space-y-1">
          {drafts.map((d) => (
            <li key={d.name}>
              <button type="button" className="text-brand-300 hover:underline" onClick={() => onSelectDraft(d.name || "")}>
                {d.name}
              </button>
              {d.is_ai_authored ? " · model drafted — you own Promote" : ""}
            </li>
          ))}
        </ul>
        <div className="mt-2 flex flex-wrap gap-2">
          {ready ? (
            <button type="button" disabled={!canPromote || busy} onClick={() => setPromoteOpen(true)} className="px-2 py-1 rounded bg-brand-700 text-white disabled:opacity-50">
              Promote
            </button>
          ) : null}
          <button type="button" disabled={!canPromote || busy} onClick={() => setPromoteOpen(true)} className="px-2 py-1 rounded bg-surface-700 text-gray-200 disabled:opacity-50">
            Promote draft
          </button>
        </div>
      </article>
      <article className="rounded-md border border-surface-700 px-3 py-2 text-sm" data-testid="suggest-demote" aria-labelledby="suggest-demote-heading">
        <h3 id="suggest-demote-heading" className="font-semibold text-gray-100">Suggest Demote</h3>
        <p className="text-gray-400 mt-1" data-testid="suggest-demote-empty">
          No effectiveness tick yet. Suggest Propose numbers land later. This is not a red alert and nothing auto-demotes.
        </p>
      </article>
      <article className="rounded-md border border-surface-700 px-3 py-2 text-sm" data-testid="live-packs" aria-labelledby="live-packs-heading">
        <h3 id="live-packs-heading" className="font-semibold text-gray-100">Live / Active packs</h3>
        <p className="text-gray-400 mt-1">Scout does not auto-demote. Propose parks. Confirm flips to Observe. A model never demotes.</p>
        {livePacks.length ? (
          <label className="block mt-2 text-xs text-gray-500">
            Live pack
            <select
              value={selectedLive}
              onChange={(e) => setSelectedLive(e.target.value)}
              className="mt-1 w-full bg-surface-900 border border-surface-600 rounded px-2 py-1 text-gray-200"
            >
              {livePacks.map((p) => (
                <option key={p._file || p.name} value={p._file || ""}>
                  {p.name || p._file}
                  {(p.lifecycle?.demote?.state || "") === "proposed" ? " (proposed)" : ""}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="mt-2 text-xs text-gray-500">No live pack to demote.</p>
        )}
        <label className="block mt-2 text-xs text-gray-500">
          Demote reason
          <input
            value={demoteReason}
            onChange={(e) => setDemoteReason(e.target.value)}
            className="mt-1 w-full bg-surface-900 border border-surface-600 rounded px-2 py-1 text-gray-200"
          />
        </label>
        {parked.map((r) => (
          <p key={r.rule_id} className="mt-1 text-gray-300">
            {r.hypothesis === "retire"
              ? `Consider taking live rule ${r.rule_id} back to Observe.`
              : `Consider this successor in Observe for ${r.rule_id}. Model suggested successor — you own Promote.`}{" "}
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
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!selectedLive || !reasonReady || busy}
            onClick={() => void proposeDemoteSelected()}
            className="px-2 py-1 rounded bg-surface-700 text-gray-200 disabled:opacity-50"
          >
            Propose Demote
          </button>
          <button
            type="button"
            data-testid="promote-undo"
            disabled={!selectedLive || !reasonReady || busy}
            onClick={() => void proposeDemoteSelected()}
            className="px-2 py-1 rounded bg-surface-700 text-gray-200 disabled:opacity-50"
          >
            Promote undo
          </button>
          <button
            type="button"
            disabled={!selectedLive || !reasonReady || !demoteProposed || busy}
            onClick={() => void confirmDemoteSelected()}
            className="px-2 py-1 rounded bg-surface-700 text-gray-200 disabled:opacity-50"
          >
            Confirm demote
          </button>
          <Link to="/rules" className="px-2 py-1 text-brand-300 hover:underline">
            Open packs
          </Link>
        </div>
      </article>
      {promoteOpen ? (
        <PromoteConfirmDialog
          packName={promoteName}
          packFile={promoteFile}
          metrics={null}
          onCancel={() => setPromoteOpen(false)}
          onConfirm={() => {
            setPromoteOpen(false);
            onPromote();
          }}
        />
      ) : null}
    </section>
  );
}
