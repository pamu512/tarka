import { useState } from "react";

import { rules } from "../api/client";
import { toUserFacingError } from "../utils/userFacingErrors";

export function L2DraftButtons({
  leftoverId = "",
  hilEventId = "",
  traceId,
  tenantId,
  overrideWhy = "",
}: {
  leftoverId?: string;
  hilEventId?: string;
  traceId: string;
  tenantId: string;
  overrideWhy?: string;
}) {
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [typedWhy, setTypedWhy] = useState("");
  const [savedWhy, setSavedWhy] = useState("");
  const ready = Boolean(traceId.trim() && (leftoverId.trim() || hilEventId.trim()));
  const why = typedWhy.trim() || overrideWhy.trim();
  const whyOk = why.length >= 8;

  async function submit(kind: "human" | "byo") {
    if (!ready || busy || !whyOk) return;
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      const out = await rules.createL2Draft(
        {
          leftover_id: leftoverId.trim(),
          hil_event_id: hilEventId.trim(),
          trace_id: traceId.trim(),
          override_why: why,
          authored_by: kind === "byo" ? "scout" : "human",
          is_ai_authored: kind === "byo",
          skip_backtest: kind === "human",
          skip_reason: kind === "human" ? why || "desk skip" : "",
        },
        tenantId,
      );
      const file = (out as { file?: string }).file || "Observe";
      setSavedWhy(why);
      setMsg(`${file} is in Observe. A human owns the next step.`);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e ?? "");
      if (/draft_exists/.test(raw)) {
        const name = /"name":\s*"([^"]+)"/.exec(raw)?.[1] || /"draft_id":\s*"([^"]+)"/.exec(raw)?.[1] || "";
        setMsg(name ? `Open draft ${name}` : "Open draft");
        return;
      }
      if (/why_required/.test(raw)) {
        setErr("Type at least 8 characters explaining why this leftover becomes an Observe draft.");
        return;
      }
      setErr(toUserFacingError(e, { subject: "Draft", action: "create Observe draft" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="l2-draft-controls" className="flex flex-wrap items-center gap-1">
      {overrideWhy.trim().length < 8 ? (
      <label className="flex items-center gap-1 text-[10px] text-gray-500">
        why
        <input
          type="text"
          data-testid="leftover-override-why"
          value={typedWhy}
          onChange={(e) => setTypedWhy(e.target.value)}
          minLength={8}
          placeholder="why this leftover becomes an Observe draft"
          className="w-44 bg-surface-900 border border-surface-600 rounded px-1.5 py-1 text-[11px] text-gray-200"
        />
      </label>
      ) : null}
      <button
        type="button"
        data-testid="draft-observe-pack"
        disabled={!ready || busy || !whyOk}
        onClick={() => void submit("human")}
        className="px-2 py-1 text-[11px] font-medium rounded-lg bg-sky-800/80 hover:bg-sky-700 disabled:opacity-50 text-sky-50"
      >
        Create draft
      </button>
      <button
        type="button"
        data-testid="l2-draft-byo"
        disabled={!ready || busy || !whyOk}
        onClick={() => void submit("byo")}
        className="px-2 py-1 text-[11px] font-medium rounded-lg bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-100"
      >
        Author via BYO
      </button>
      {savedWhy ? (
        <span data-testid="leftover-saved-why" className="text-[11px] text-gray-300">
          {savedWhy}
        </span>
      ) : null}
      {err ? (
        <span className="text-[11px] text-rose-300" role="alert">
          {err}
        </span>
      ) : null}
      {msg ? (
        /Open draft/.test(msg) ? (
          <a href="/ops/shadow" className="text-[11px] text-brand-300 hover:underline" data-testid="open-existing-draft">
            {msg}
          </a>
        ) : (
          <span className="text-[11px] text-gray-400">{msg}</span>
        )
      ) : null}
    </div>
  );
}
