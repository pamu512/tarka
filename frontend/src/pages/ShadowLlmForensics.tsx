import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  SHADOW_LLM_STREAM_URL,
  streamShadowLLMChat,
  type ShadowSidecarChatMessage,
  type ShadowSidecarStreamEvent,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { toUserFacingError } from "../utils/userFacingErrors";

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

export default function ShadowLlmForensics() {
  const [forensicNotes, setForensicNotes] = useState("");
  const [caseId, setCaseId] = useState("");
  const [messages, setMessages] = useState<ShadowSidecarChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [conn, setConn] = useState<ConnState>("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastEventSummary, setLastEventSummary] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const gotFinalRef = useRef(false);
  const threadId = useMemo(
    () => `tarka-forensics-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 11)}`,
    [],
  );

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

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
          case_id: caseId.trim() || undefined,
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
              const dbg = ev.payload?.debug;
              setLastEventSummary(
                dbg && typeof dbg === "object"
                  ? `thread_id=${String((dbg as { thread_id?: string }).thread_id ?? "")} checkpoint_skip=${String((dbg as { checkpoint_skip?: boolean }).checkpoint_skip ?? "")}`
                  : "final",
              );
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
          "Stream closed before a final frame. The sidecar may have restarted, the proxy may have dropped the connection, or the graph finished without emitting `final`.",
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

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-950 text-gray-200">
      <div className="shrink-0 border-b border-surface-700 px-6 py-4">
        <PageTitle module="investigation">Shadow LLM streaming forensics</PageTitle>
        <p className="mt-2 text-sm text-gray-500 max-w-3xl">
          Split view: local notes and stream health on the left; Shadow sidecar chat on the right. Streams over SSE
          from <code className="text-gray-400">{SHADOW_LLM_STREAM_URL}</code> (Vite → <code className="text-gray-400">127.0.0.1:8742</code>). Start the
          Shadow API and Ollama (or compatible host) before sending.
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <section className="flex min-h-[220px] w-full min-w-0 flex-col border-b border-surface-700 lg:w-[42%] lg:border-b-0 lg:border-r">
          <div className="shrink-0 px-4 py-3 border-b border-surface-800 bg-surface-900/80">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Forensic pad (local only)</h2>
          </div>
          <textarea
            className="min-h-0 flex-1 resize-none bg-surface-900/40 px-4 py-3 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
            placeholder="Timestamps, hypotheses, artifact IDs — not sent to the model."
            value={forensicNotes}
            onChange={(e) => setForensicNotes(e.target.value)}
            spellCheck={false}
          />
          <div className="shrink-0 space-y-2 border-t border-surface-800 bg-surface-900/60 px-4 py-3">
            <label className="block text-xs text-gray-500">
              Optional case id (passed to sidecar as <code className="text-gray-400">case_id</code>)
              <input
                className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-950 px-3 py-2 text-sm text-gray-200"
                value={caseId}
                onChange={(e) => setCaseId(e.target.value)}
                placeholder="e.g. active case UUID from Shadow"
              />
            </label>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-gray-500">Connection:</span>
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${
                  conn === "streaming"
                    ? "bg-amber-500/20 text-amber-200"
                    : conn === "error" || conn === "dropped"
                      ? "bg-rose-500/20 text-rose-200"
                      : conn === "aborted"
                        ? "bg-surface-600 text-gray-300"
                        : "bg-emerald-500/15 text-emerald-200"
                }`}
              >
                {conn}
              </span>
              {lastEventSummary ? <span className="text-gray-600 truncate max-w-[min(100%,18rem)]">{lastEventSummary}</span> : null}
            </div>
            {lastError ? (
              <div className="rounded-lg border border-rose-500/30 bg-rose-950/30 px-3 py-2 text-xs text-rose-100">{lastError}</div>
            ) : null}
            <p className="text-[11px] text-gray-600 leading-relaxed">
              If the stream stalls or drops, confirm uvicorn on 8742 and the Vite proxy. Retrying sends the full transcript; rotate thread in the sidecar UI if checkpoints desync.
            </p>
          </div>
        </section>

        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.length === 0 && !streamingText ? (
              <p className="text-sm text-gray-500">No messages yet. Ask a question to begin streaming.</p>
            ) : null}
            {messages.map((m, i) => (
              <div
                key={`${i}-${m.role}-${m.content.slice(0, 24)}`}
                className={`max-w-[min(100%,48rem)] rounded-xl border px-4 py-3 text-sm whitespace-pre-wrap ${
                  m.role === "user"
                    ? "ml-auto border-brand-500/30 bg-brand-950/40 text-gray-100"
                    : "mr-auto border-surface-600 bg-surface-900/80 text-gray-200"
                }`}
              >
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">{m.role}</div>
                {m.content}
              </div>
            ))}
            {streamingText ? (
              <div className="mr-auto max-w-[min(100%,48rem)] rounded-xl border border-amber-500/35 bg-amber-950/20 px-4 py-3 text-sm whitespace-pre-wrap">
                <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-amber-200/90">
                  <span>assistant (streaming)</span>
                  <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" aria-hidden />
                </div>
                {streamingText}
              </div>
            ) : null}
          </div>

          <div className="shrink-0 border-t border-surface-700 bg-surface-900/50 px-4 py-3">
            <div className="flex flex-wrap items-end gap-2">
              <textarea
                className="min-h-[44px] flex-1 min-w-[12rem] resize-y rounded-xl border border-surface-600 bg-surface-950 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                rows={2}
                placeholder="Message Shadow LLM…"
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
                className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 disabled:opacity-40"
                disabled={busy || !draft.trim()}
                onClick={() => void send()}
              >
                Send
              </button>
              <button
                type="button"
                className="rounded-xl border border-surface-500 bg-surface-800 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-surface-700 disabled:opacity-40"
                disabled={!busy}
                onClick={stopGeneration}
              >
                Stop generation
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
