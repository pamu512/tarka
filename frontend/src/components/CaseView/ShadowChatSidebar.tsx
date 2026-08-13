import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from 'react-router';
import { investigation, orchestrator } from "../../api/client";
import { MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK } from "../../utils/inferInvestigationPlaybook";
import { toUserFacingError } from "../../utils/userFacingErrors";

type ConnState = "idle" | "streaming" | "complete" | "aborted" | "dropped" | "error";

type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  agent_run_id?: string;
};

type PlaybookOption = { id: string; title: string; vertical: string };

type CaseStatusProposal = {
  proposal_id: string;
  to_status: string;
  reason_code: string;
  status: string;
  agent_run_id: string;
};

const GRAPH_MISSING_BANNER =
  "Graph neighborhood missing — narratives are ungrounded; status changes and promote stay blocked.";

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

const DEFAULT_ANALYST = "analyst-1";

export type ShadowChatSidebarProps = {
  caseId: string;
  tenantId: string;
  caseTitle?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When true, render inline panel body (workbench copilot rail) without fixed overlay chrome. */
  embedded?: boolean;
  /** Tag-inferred playbook id (e.g. marketplace_cod_courier_hold); applied when selection is empty. */
  suggestedPlaybookId?: string | null;
};

/**
 * Case-detail right rail: streaming chat with investigation-agent for this case.
 * (Historically named ShadowChatSidebar; runtime is investigation-agent, not tools/shadow.)
 */
export function ShadowChatSidebar({
  caseId,
  tenantId,
  caseTitle,
  open,
  onOpenChange,
  embedded = false,
  suggestedPlaybookId = null,
}: ShadowChatSidebarProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [conn, setConn] = useState<ConnState>("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastAgentRunId, setLastAgentRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<string | null>(null);
  const [playbooks, setPlaybooks] = useState<PlaybookOption[]>([]);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState("");
  const [graphMissing, setGraphMissing] = useState(false);
  const [proposals, setProposals] = useState<CaseStatusProposal[]>([]);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const gotFinalRef = useRef(false);
  const draftRef = useRef<HTMLTextAreaElement | null>(null);
  const userPickedPlaybookRef = useRef(false);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    void investigation
      .listPlaybooks()
      .then((r) => setPlaybooks(r.playbooks ?? []))
      .catch(() => setPlaybooks([]));
  }, []);

  useEffect(() => {
    if (userPickedPlaybookRef.current) return;
    if (suggestedPlaybookId) {
      setSelectedPlaybookId(suggestedPlaybookId);
    }
  }, [suggestedPlaybookId]);

  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => draftRef.current?.focus(), 80);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [open]);

  const loadProposals = useCallback(async () => {
    if (!caseId.trim() || !tenantId.trim()) {
      setProposals([]);
      return;
    }
    try {
      const body = await investigation.listCaseStatusProposals(caseId.trim(), tenantId.trim());
      setProposals(body.items ?? []);
      setProposalError(null);
    } catch (e: unknown) {
      setProposals([]);
      setProposalError(
        toUserFacingError(e, {
          subject: "Case status proposals",
          action: "load status proposals",
        }),
      );
    }
  }, [caseId, tenantId]);

  useEffect(() => {
    void loadProposals();
  }, [loadProposals]);

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setConn((c) => (c === "streaming" ? "aborted" : c));
  }, []);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || conn === "streaming") return;
    const userMsg: ChatMessage = { role: "user", content: text };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setDraft("");
    setStreamingText("");
    setLastError(null);
    gotFinalRef.current = false;
    const ac = new AbortController();
    abortRef.current = ac;
    setConn("streaming");

    try {
      const result = await investigation.chatWithHistoryStream(
        nextMessages,
        tenantId,
        DEFAULT_ANALYST,
        caseId.trim() || undefined,
        {
          signal: ac.signal,
          playbook_id: selectedPlaybookId || undefined,
        },
        (ev) => {
          if (ev.type === "delta" && ev.payload && typeof ev.payload === "object") {
            const t = (ev.payload as { text?: string }).text;
            if (t) setStreamingText((s) => s + t);
          } else if (ev.type === "final" && ev.payload && typeof ev.payload === "object") {
            const p = ev.payload as { reply?: string; agent_run_id?: string };
            const reply = typeof p.reply === "string" ? p.reply : "";
            const rid = typeof p.agent_run_id === "string" ? p.agent_run_id : undefined;
            gotFinalRef.current = true;
            if (rid) setLastAgentRunId(rid);
            if (reply) {
              setMessages([
                ...nextMessages,
                { role: "assistant", content: reply, agent_run_id: rid },
              ]);
              setStreamingText("");
            }
          } else if (ev.type === "error" && ev.payload && typeof ev.payload === "object") {
            const err = ev.payload as { code?: string; message?: string };
            const msg = err.message ?? "Stream error";
            setLastError(err.code ? `${err.code}: ${msg}` : msg);
          }
        },
      );
      if (!gotFinalRef.current && result.reply) {
        gotFinalRef.current = true;
        const rid =
          typeof result.agent_run_id === "string" ? result.agent_run_id : undefined;
        if (rid) setLastAgentRunId(rid);
        setMessages([
          ...nextMessages,
          { role: "assistant", content: result.reply, agent_run_id: rid },
        ]);
        setStreamingText("");
      }
      const rid =
        typeof result.agent_run_id === "string" ? result.agent_run_id : undefined;
      if (typeof result.graph_missing === "boolean") {
        setGraphMissing(result.graph_missing);
      } else if (rid) {
        try {
          const run = await investigation.getAgentRun(rid, tenantId);
          setGraphMissing(Boolean(run.graph_missing));
        } catch {
          setGraphMissing(false);
        }
      } else {
        setGraphMissing(false);
      }
      if (!gotFinalRef.current && !ac.signal.aborted) {
        setConn("dropped");
        setLastError(
          "Stream closed before a final frame. Ensure investigation-agent is reachable via /api/investigation.",
        );
      } else {
        setConn(ac.signal.aborted ? "aborted" : "complete");
      }
      void loadProposals();
    } catch (e: unknown) {
      if (isAbortError(e)) {
        setConn("aborted");
        setLastError(null);
      } else {
        setConn("error");
        setLastError(
          toUserFacingError(e, {
            subject: "Investigation copilot",
            action: "reach investigation-agent",
          }),
        );
      }
    } finally {
      abortRef.current = null;
      setStreamingText((t) => (gotFinalRef.current ? "" : t));
    }
  }, [caseId, conn, draft, loadProposals, messages, selectedPlaybookId, tenantId]);

  const confirmProposal = useCallback(
    async (p: CaseStatusProposal) => {
      if (confirmingId) return;
      setConfirmingId(p.proposal_id);
      setProposalError(null);
      try {
        await orchestrator.putCaseStatus(caseId.trim(), p.to_status, p.reason_code);
        await investigation.ackCaseStatusProposal(p.proposal_id, tenantId.trim(), "confirmed");
        await loadProposals();
      } catch (e: unknown) {
        setProposalError(
          toUserFacingError(e, {
            subject: "Case status proposal",
            action: "confirm lifecycle status",
          }),
        );
      } finally {
        setConfirmingId(null);
      }
    },
    [caseId, confirmingId, loadProposals, tenantId],
  );

  const busy = conn === "streaming";
  const investigationHref = `/investigation?case_id=${encodeURIComponent(caseId)}&tenant_id=${encodeURIComponent(tenantId)}`;
  const showCodSuggestion =
    suggestedPlaybookId === MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK &&
    selectedPlaybookId === MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK;

  const rail = (
    <div className="flex h-full min-h-0 shrink-0 flex-col border-surface-700 bg-surface-900/90 xl:border-l">
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        className="flex min-h-[12rem] flex-1 flex-col items-center justify-start gap-3 py-4 text-brand-300 transition hover:bg-surface-800/80 hover:text-brand-200"
        title="Open investigation copilot"
      >
        <span
          className="text-[11px] font-semibold uppercase tracking-widest text-brand-400/90"
          style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
        >
          Copilot
        </span>
        <span className="text-lg leading-none text-gray-500" aria-hidden>
          ‹
        </span>
      </button>
    </div>
  );

  const panel = open ? (
    <div
      data-hotkeys-ignore
      className="flex h-full max-h-[100dvh] min-h-0 w-[min(22rem,calc(100vw-1rem))] shrink-0 flex-col border-surface-700 bg-surface-900 shadow-2xl shadow-black/40 xl:w-[22rem] xl:border-l xl:shadow-none"
    >
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-surface-700 px-3 py-2.5">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Investigation copilot
          </h2>
          <p className="truncate text-[11px] text-gray-500" title={caseTitle ?? caseId}>
            {caseTitle ? caseTitle : `Case ${caseId.slice(0, 8)}…`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="shrink-0 rounded-lg border border-surface-600 px-2 py-1 text-[11px] font-medium text-gray-400 hover:bg-surface-800 hover:text-gray-200"
          aria-label="Close investigation copilot"
        >
          Close
        </button>
      </div>

      {graphMissing ? (
        <div className="shrink-0 border-b border-amber-500/40 bg-amber-950/30 px-3 py-2 text-[11px] leading-relaxed text-amber-100">
          {GRAPH_MISSING_BANNER}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3">
        <p className="text-[11px] leading-relaxed text-gray-500">
          Ask about this case — grounded via investigation-agent tools and{" "}
          <code className="text-gray-400">case_id</code>.
        </p>
        {messages.length === 0 && !streamingText ? (
          <p className="text-sm text-gray-600">No messages yet.</p>
        ) : null}
        {messages.map((m, i) => (
          <div
            key={`${i}-${m.role}-${m.content.slice(0, 24)}`}
            className={`max-w-full rounded-xl border px-3 py-2.5 text-xs whitespace-pre-wrap ${
              m.role === "user"
                ? "ml-4 border-brand-500/30 bg-brand-950/35 text-gray-100"
                : "mr-4 border-surface-600 bg-surface-950/80 text-gray-200"
            }`}
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
              {m.role}
            </div>
            {m.content}
            {m.agent_run_id ? (
              <div className="mt-2 break-all font-mono text-[10px] text-brand-300/90">
                agent_run_id: {m.agent_run_id}
              </div>
            ) : null}
          </div>
        ))}
        {streamingText ? (
          <div className="mr-4 max-w-full rounded-xl border border-amber-500/35 bg-amber-950/25 px-3 py-2.5 text-xs whitespace-pre-wrap">
            <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-amber-200/90">
              <span>assistant (streaming)</span>
              <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" aria-hidden />
            </div>
            {streamingText}
          </div>
        ) : null}
      </div>

      {lastError ? (
        <div className="shrink-0 border-t border-surface-800 px-3 py-2 text-[11px] text-rose-200">
          {lastError}
        </div>
      ) : null}

      {lastAgentRunId ? (
        <div className="shrink-0 space-y-1 border-t border-surface-800 px-3 py-2 text-[10px] text-gray-400">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-brand-300">agent_run_id: {lastAgentRunId}</span>
            <button
              type="button"
              className="rounded border border-surface-600 px-1.5 py-0.5 text-gray-300 hover:bg-surface-800"
              onClick={() => {
                void (async () => {
                  try {
                    const run = await investigation.getAgentRun(lastAgentRunId, tenantId);
                    const keys = (run.context_snapshot?.keys_present ?? []).join(", ") || "—";
                    const fresh = JSON.stringify(run.context_snapshot?.freshness ?? {});
                    setRunDetail(`keys_present=[${keys}] freshness=${fresh}`);
                  } catch (e) {
                    setRunDetail(
                      toUserFacingError(e, { subject: "AgentRun", action: "GET /v1/agent-runs" }),
                    );
                  }
                })();
              }}
            >
              View run
            </button>
          </div>
          {runDetail ? <p className="break-all text-gray-500">{runDetail}</p> : null}
        </div>
      ) : null}

      {proposalError ? (
        <div className="shrink-0 border-t border-surface-800 px-3 py-2 text-[11px] text-rose-200">
          {proposalError}
        </div>
      ) : null}

      {proposals.some((p) => p.status === "pending") ? (
        <div className="shrink-0 space-y-1.5 border-t border-surface-800 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Status proposals
          </p>
          {proposals
            .filter((p) => p.status === "pending")
            .map((p) => (
              <div
                key={p.proposal_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-surface-700 bg-surface-950/60 px-2 py-1.5"
              >
                <div className="min-w-0 text-[11px] text-gray-300">
                  <div className="font-mono">
                    {p.to_status}
                    <span className="ml-1 text-gray-500">{p.reason_code}</span>
                  </div>
                </div>
                <button
                  type="button"
                  className="rounded border border-brand-500/40 bg-brand-600/80 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-brand-500 disabled:opacity-40"
                  disabled={confirmingId !== null}
                  onClick={() => void confirmProposal(p)}
                >
                  {confirmingId === p.proposal_id ? "Confirming…" : "Confirm"}
                </button>
              </div>
            ))}
        </div>
      ) : null}

      <div className="shrink-0 space-y-2 border-t border-surface-700 bg-surface-950/50 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-gray-500">
          <span>Stream:</span>
          <span
            className={`rounded-full px-2 py-0.5 font-medium ${
              conn === "streaming"
                ? "bg-amber-500/20 text-amber-200"
                : conn === "error" || conn === "dropped"
                  ? "bg-rose-500/20 text-rose-200"
                  : "bg-emerald-500/15 text-emerald-200"
            }`}
          >
            {conn}
          </span>
        </div>
        <label className="block text-[10px] text-gray-500">
          Playbook
          <select
            value={selectedPlaybookId}
            disabled={busy}
            onChange={(e) => {
              userPickedPlaybookRef.current = true;
              setSelectedPlaybookId(e.target.value);
            }}
            title="Typology workflow hints (GET /v1/playbooks)"
            className="mt-1 w-full rounded-md border border-surface-600 bg-surface-950 px-2 py-1.5 text-[11px] text-gray-200"
            data-testid="case-copilot-playbook"
          >
            <option value="">None</option>
            {playbooks.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        {showCodSuggestion ? (
          <p
            className="text-[10px] text-amber-200/90 border border-amber-500/30 rounded-md px-2 py-1 bg-amber-950/20"
            data-testid="case-copilot-playbook-suggestion"
          >
            Suggested: marketplace COD / courier hold (from case tags)
          </p>
        ) : null}
        <div className="flex flex-wrap items-end gap-2">
          <textarea
            ref={draftRef}
            className="min-h-[52px] flex-1 min-w-0 resize-y rounded-lg border border-surface-600 bg-surface-950 px-2.5 py-2 text-xs text-gray-100 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
            rows={2}
            placeholder='e.g. "Why was this device flagged as a mule?"'
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button
            type="button"
            className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-medium text-white hover:bg-brand-500 disabled:opacity-40"
            disabled={busy || !draft.trim()}
            onClick={() => void send()}
          >
            Send
          </button>
          <button
            type="button"
            className="rounded-lg border border-surface-500 bg-surface-800 px-3 py-2 text-xs font-medium text-gray-200 hover:bg-surface-700 disabled:opacity-40"
            disabled={!busy}
            onClick={stopGeneration}
          >
            Stop
          </button>
        </div>
        <Link to={investigationHref} className="inline-block text-[11px] text-brand-400 hover:text-brand-300">
          Full Investigation workspace →
        </Link>
      </div>
    </div>
  ) : null;

  if (embedded && open) {
    return (
      <div className="flex min-h-[14rem] max-h-[40vh] flex-col border-b border-surface-700/80">
        {panel}
      </div>
    );
  }

  return (
    <>
      {open ? (
        <button
          type="button"
          className="fixed inset-0 z-[180] bg-black/45 xl:hidden"
          aria-label="Dismiss investigation copilot"
          onClick={() => onOpenChange(false)}
        />
      ) : null}

      {!open ? (
        <>
          <button
            type="button"
            className="fixed bottom-5 right-5 z-[160] flex items-center gap-2 rounded-full border border-brand-500/40 bg-brand-600/90 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-black/40 xl:hidden"
            onClick={() => onOpenChange(true)}
          >
            Copilot
          </button>
          <div className="hidden shrink-0 self-stretch xl:flex xl:w-12">{rail}</div>
        </>
      ) : (
        <div className="fixed inset-y-0 right-0 z-[190] flex h-full max-h-[100dvh] min-h-0 xl:static xl:inset-auto xl:z-auto xl:h-full xl:max-h-none">
          {panel}
        </div>
      )}
    </>
  );
}
