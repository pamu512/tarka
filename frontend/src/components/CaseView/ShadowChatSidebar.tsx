import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  streamShadowLLMChat,
  type ShadowSidecarChatMessage,
  type ShadowSidecarStreamEvent,
} from "../../api/client";
import { toUserFacingError } from "../../utils/userFacingErrors";

type ConnState = "idle" | "streaming" | "complete" | "aborted" | "dropped" | "error";

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

function normalizeFinalMessages(raw: unknown): ShadowSidecarChatMessage[] {
  if (!Array.isArray(raw)) return [];
  const out: ShadowSidecarChatMessage[] = [];
  for (const m of raw) {
    if (typeof m !== "object" || m == null) continue;
    const role = (m as { role?: string }).role;
    const content = (m as { content?: string }).content;
    if (role !== "user" && role !== "assistant" && role !== "system") continue;
    if (typeof content !== "string") continue;
    out.push({ role, content });
  }
  return out;
}

export type ShadowChatSidebarProps = {
  caseId: string;
  tenantId: string;
  caseTitle?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * Case-detail right rail: streaming chat with the Shadow sidecar for this case (`case_id` on every request).
 */
export function ShadowChatSidebar({ caseId, tenantId, caseTitle, open, onOpenChange }: ShadowChatSidebarProps) {
  const [messages, setMessages] = useState<ShadowSidecarChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [conn, setConn] = useState<ConnState>("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const gotFinalRef = useRef(false);
  const draftRef = useRef<HTMLTextAreaElement | null>(null);

  const threadId = useMemo(() => `tarka-case-sidebar-${caseId}`, [caseId]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => draftRef.current?.focus(), 80);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [open]);

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setConn((c) => (c === "streaming" ? "aborted" : c));
  }, []);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || conn === "streaming") return;
    const userMsg: ShadowSidecarChatMessage = { role: "user", content: text };
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
      await streamShadowLLMChat(
        {
          messages: nextMessages,
          case_id: caseId.trim(),
          thread_id: threadId,
        },
        {
          signal: ac.signal,
          onEvent: (ev: ShadowSidecarStreamEvent) => {
            if (ev.type === "delta") {
              const t = ev.payload?.text;
              if (t) setStreamingText((s) => s + t);
            } else if (ev.type === "final") {
              gotFinalRef.current = true;
              const normalized = normalizeFinalMessages(ev.payload?.messages);
              if (normalized.length) setMessages(normalized);
              setStreamingText("");
            } else if (ev.type === "error") {
              const code = ev.payload?.code;
              const msg = ev.payload?.message ?? "Stream error";
              setLastError(code ? `${code}: ${msg}` : msg);
            }
          },
        },
      );
      if (!gotFinalRef.current && !ac.signal.aborted) {
        setConn("dropped");
        setLastError(
          "Stream closed before a final frame. Ensure the Shadow sidecar is running (e.g. port 8742 via Vite proxy).",
        );
      } else {
        setConn(ac.signal.aborted ? "aborted" : "complete");
      }
    } catch (e: unknown) {
      if (isAbortError(e)) {
        setConn("aborted");
        setLastError(null);
      } else {
        setConn("error");
        setLastError(toUserFacingError(e, { subject: "Shadow LLM stream", action: "reach the sidecar or LLM" }));
      }
    } finally {
      abortRef.current = null;
      setStreamingText((t) => (gotFinalRef.current ? "" : t));
    }
  }, [caseId, conn, draft, messages, threadId]);

  const busy = conn === "streaming";
  const forensicsHref = `/investigation/shadow-llm?case_id=${encodeURIComponent(caseId)}&tenant_id=${encodeURIComponent(tenantId)}`;

  const rail = (
    <div className="flex h-full min-h-0 shrink-0 flex-col border-surface-700 bg-surface-900/90 xl:border-l">
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        className="flex min-h-[12rem] flex-1 flex-col items-center justify-start gap-3 py-4 text-brand-300 transition hover:bg-surface-800/80 hover:text-brand-200"
        title="Open Shadow AI chat"
      >
        <span
          className="text-[11px] font-semibold uppercase tracking-widest text-brand-400/90"
          style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
        >
          Shadow AI
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
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Shadow AI</h2>
          <p className="truncate text-[11px] text-gray-500" title={caseTitle ?? caseId}>
            {caseTitle ? caseTitle : `Case ${caseId.slice(0, 8)}…`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="shrink-0 rounded-lg border border-surface-600 px-2 py-1 text-[11px] font-medium text-gray-400 hover:bg-surface-800 hover:text-gray-200"
          aria-label="Close Shadow AI sidebar"
        >
          Close
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3">
        <p className="text-[11px] leading-relaxed text-gray-500">
          Ask why signals fired — e.g. why this device was flagged as a mule. Answers use this case&apos;s{" "}
          <code className="text-gray-400">case_id</code> on the Shadow sidecar.
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
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">{m.role}</div>
            {m.content}
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
        <div className="shrink-0 border-t border-surface-800 px-3 py-2 text-[11px] text-rose-200">{lastError}</div>
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
        <Link to={forensicsHref} className="inline-block text-[11px] text-brand-400 hover:text-brand-300">
          Full Shadow LLM workspace →
        </Link>
      </div>
    </div>
  ) : null;

  return (
    <>
      {open ? (
        <button
          type="button"
          className="fixed inset-0 z-[180] bg-black/45 xl:hidden"
          aria-label="Dismiss Shadow AI"
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
            Shadow AI
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