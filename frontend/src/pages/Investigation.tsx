import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  admin,
  investigation,
  type InvestigationAnswerSections,
  type InvestigationClaim,
  type InvestigationClaimSupportRow,
  type InvestigationGovernanceInfo,
  type InvestigationSourceRefCard,
} from "../api/client";
import { buildPlatformAuditForCopilot, type CopilotContextFlags } from "../utils/copilotContext";
import {
  buildRepeatSkillSuggestionPrompt,
  buildSkillCommandHelp,
  COPILOT_SKILL_GROUPS,
  findCopilotSkillByQuery,
  formatSkillDetail,
  normalizePromptForRepeatDetection,
  parseSkillCommand,
  QUICK_INSTANT_SKILLS,
} from "../config/copilotSkills";
import { PageTitle } from "../components/PageTitle";
import { ModuleIcon } from "../components/ModuleIcon";

interface ToolCall {
  name: string;
  arguments: string;
  result?: string;
}

const DEFAULT_TENANT = "demo";
const DEFAULT_ANALYST = "analyst-1";

/** API returns `{ tool, args, result }`; UI uses `{ name, arguments, result }`. */
function normalizeToolCalls(raw: unknown): ToolCall[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((tc: Record<string, unknown>) => {
    const name = String(tc.name ?? tc.tool ?? "unknown");
    let argStr = "";
    if (typeof tc.arguments === "string") argStr = tc.arguments;
    else if (tc.args != null) argStr = JSON.stringify(tc.args, null, 2);
    let resStr: string | undefined;
    if (tc.result !== undefined && tc.result !== null) {
      resStr = typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2);
    }
    return { name, arguments: argStr, result: resStr };
  });
}

type MessageBubbleKind = "default" | "system_help" | "repeat_hint";

function normalizeCopilotClaims(raw: unknown): InvestigationClaim[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((c): c is Record<string, unknown> => typeof c === "object" && c != null)
    .map((c) => ({
      text: String(c.text ?? "").trim(),
      source: (c.source === "tool" ? "tool" : "unknown") as InvestigationClaim["source"],
    }))
    .filter((c) => c.text.length > 0);
}

function normalizeSourceRefs(raw: unknown): InvestigationSourceRefCard[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x): x is Record<string, unknown> => typeof x === "object" && x != null)
    .map((x) => ({
      tool: String(x.tool ?? ""),
      ok: x.ok === true,
      case_id: x.case_id != null ? String(x.case_id) : undefined,
      entity_id: x.entity_id != null ? String(x.entity_id) : undefined,
      trace_id: x.trace_id != null ? String(x.trace_id) : undefined,
      batch_id: x.batch_id != null ? String(x.batch_id) : undefined,
      error: x.error != null ? String(x.error) : undefined,
    }))
    .filter((c) => c.tool.length > 0);
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCall[];
  /** Structured factual claims; `tool` = model attests tool-backed, `unknown` = unverified. */
  claims?: InvestigationClaim[];
  /** Structured tool-touch summary from the agent (audit transparency). */
  source_refs?: InvestigationSourceRefCard[];
  /** Server playbook id when one was active for this turn. */
  playbook_id?: string;
  turn_id?: string;
  answer_sections?: InvestigationAnswerSections;
  claims_deterministic_support?: InvestigationClaimSupportRow[];
  tool_acknowledgment_warnings?: string[];
  judge_assessments?: unknown;
  timestamp: Date;
  /** Rich formatting for /skill output and repeat-task hints */
  bubble?: MessageBubbleKind;
}

export default function Investigation() {
  const [searchParams] = useSearchParams();
  const contextCaseId = searchParams.get("case_id") ?? undefined;
  const contextTenantId = searchParams.get("tenant_id") ?? DEFAULT_TENANT;

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationHistory, setConversationHistory] = useState<{ role: string; content: string }[]>([]);
  const [trackHistoricalActions, setTrackHistoricalActions] = useState(true);
  const [onlySessionAudit, setOnlySessionAudit] = useState(false);
  const [skipSessionActions, setSkipSessionActions] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  /** Browser session start for “only this session” audit scope (reset on Clear chat). */
  const sessionStartedAtRef = useRef<string>(new Date().toISOString());
  /** Count normalized user prompts to suggest custom skills on repeats */
  const userPromptCountsRef = useRef<Record<string, number>>({});
  const repeatHintShownRef = useRef<Set<string>>(new Set());
  const batchFileRef = useRef<HTMLInputElement>(null);
  const [activeBatch, setActiveBatch] = useState<{
    batchId: string;
    rowCount: number;
    filename: string;
    columnCount: number;
  } | null>(null);
  const [batchUploadBusy, setBatchUploadBusy] = useState(false);
  const [governanceInfo, setGovernanceInfo] = useState<InvestigationGovernanceInfo | null>(null);
  const [playbooks, setPlaybooks] = useState<Array<{ id: string; title: string; vertical: string }>>([]);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>("");
  const [useStreamReply, setUseStreamReply] = useState(false);
  const [memoTitle, setMemoTitle] = useState("");
  const [memoBody, setMemoBody] = useState("");
  const [memoBusy, setMemoBusy] = useState(false);
  const [feedbackWindowDays, setFeedbackWindowDays] = useState(7);
  const [feedbackSummary, setFeedbackSummary] = useState<{
    tenant_id: string;
    window_days: number;
    total: number;
    by_rating: Record<string, number>;
    avg_rating: number | null;
  } | null>(null);
  const [feedbackRecent, setFeedbackRecent] = useState<
    Array<{
      id: number;
      turn_id: string;
      analyst_id: string;
      rating: number;
      note: string | null;
      claim_indices: number[] | null;
      created_at: number;
      case_id: string | null;
      playbook_id: string | null;
    }>
  >([]);
  const [feedbackAnalyticsLoading, setFeedbackAnalyticsLoading] = useState(false);
  const [feedbackAnalyticsError, setFeedbackAnalyticsError] = useState<string | null>(null);

  const viteGovProfile = import.meta.env.VITE_AI_GOVERNANCE_PROFILE as string | undefined;
  const viteGovLabels: Record<string, string> = {
    us: "United States",
    eu_uk: "EU / UK",
    global: "Global",
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    void investigation
      .governance()
      .then((g) => setGovernanceInfo(g))
      .catch(() => setGovernanceInfo(null));
  }, []);

  useEffect(() => {
    void investigation
      .listPlaybooks()
      .then((r) => setPlaybooks(r.playbooks ?? []))
      .catch(() => setPlaybooks([]));
  }, []);

  const loadFeedbackAnalytics = useCallback(async () => {
    setFeedbackAnalyticsLoading(true);
    setFeedbackAnalyticsError(null);
    try {
      const [sum, rec] = await Promise.all([
        investigation.getFeedbackSummary(contextTenantId, feedbackWindowDays),
        investigation.getFeedbackRecent(contextTenantId, 25),
      ]);
      setFeedbackSummary(sum);
      setFeedbackRecent(rec.items ?? []);
    } catch (e) {
      setFeedbackAnalyticsError(e instanceof Error ? e.message : "Failed to load feedback analytics");
      setFeedbackSummary(null);
      setFeedbackRecent([]);
    } finally {
      setFeedbackAnalyticsLoading(false);
    }
  }, [contextTenantId, feedbackWindowDays]);

  useEffect(() => {
    void loadFeedbackAnalytics();
  }, [loadFeedbackAnalytics]);

  const handleNewSession = () => {
    setMessages([]);
    setConversationHistory([]);
    setInput("");
    setActiveBatch(null);
    setSelectedPlaybookId("");
    sessionStartedAtRef.current = new Date().toISOString();
    userPromptCountsRef.current = {};
    repeatHintShownRef.current = new Set();
  };

  const handleMemoSave = async () => {
    const body = memoBody.trim();
    if (!body) return;
    setMemoBusy(true);
    try {
      await investigation.ingestKnowledgeMemo(memoTitle.trim() || "Memo", body, contextTenantId, DEFAULT_ANALYST);
      setMemoTitle("");
      setMemoBody("");
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            "Investigation memo saved for this tenant and analyst. Ask the copilot to use **search_knowledge** with keywords from your memo.",
          timestamp: new Date(),
        },
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Memo save failed";
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Memo upload error: ${msg}`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setMemoBusy(false);
    }
  };

  const handleBatchFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBatchUploadBusy(true);
    try {
      const r = await investigation.ingestBatch(file, contextTenantId, DEFAULT_ANALYST);
      setActiveBatch({
        batchId: r.batch_id,
        rowCount: r.row_count,
        filename: r.filename,
        columnCount: r.columns?.length ?? 0,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Batch upload error: ${msg}`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setBatchUploadBusy(false);
    }
  };

  const sendMessage = async (rawText: string) => {
    const text = rawText.trim();
    if (!text || sending) return;

    const skillCmd = parseSkillCommand(text);
    if (skillCmd.isSkillCommand) {
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };
      let body: string;
      const rest = skillCmd.rest;
      if (!rest || rest.toLowerCase() === "help" || rest.toLowerCase() === "list") {
        body = buildSkillCommandHelp();
      } else {
        const found = findCopilotSkillByQuery(rest);
        body = found ? formatSkillDetail(found) : `No preset matched "${rest}".\n\n${buildSkillCommandHelp()}`;
      }
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: body,
        timestamp: new Date(),
        bubble: "system_help",
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInput("");
      return;
    }

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    const updatedHistory = [...conversationHistory, { role: "user", content: text }];
    setConversationHistory(updatedHistory);

    const norm = normalizePromptForRepeatDetection(text);
    userPromptCountsRef.current[norm] = (userPromptCountsRef.current[norm] ?? 0) + 1;
    const repeatCount = userPromptCountsRef.current[norm];

    try {
      const ctxFlags: CopilotContextFlags = {
        trackHistoricalActions: trackHistoricalActions,
        onlySession: onlySessionAudit,
        skipSessionActions,
      };

      let platformAudit: Awaited<ReturnType<typeof admin.auditLog>>["items"] = [];
      if (trackHistoricalActions) {
        try {
          const auditRes = await admin.auditLog();
          platformAudit = auditRes.items ?? [];
        } catch {
          /* optional feed — copilot still works without it */
        }
      }

      const auditPayload = buildPlatformAuditForCopilot(
        platformAudit,
        ctxFlags,
        sessionStartedAtRef.current,
        40,
      );

      const chatOpts = {
        platform_audit: auditPayload,
        batch_id: activeBatch?.batchId,
        playbook_id: selectedPlaybookId || undefined,
        context_options: {
          track_historical_actions: trackHistoricalActions,
          only_session: onlySessionAudit,
          skip_session_actions: skipSessionActions,
          session_started_at: onlySessionAudit ? sessionStartedAtRef.current : null,
        },
      };
      const data = useStreamReply
        ? await investigation.chatWithHistoryStream(
            updatedHistory,
            contextTenantId,
            DEFAULT_ANALYST,
            contextCaseId,
            chatOpts,
          )
        : await investigation.chatWithHistory(
            updatedHistory,
            contextTenantId,
            DEFAULT_ANALYST,
            contextCaseId,
            chatOpts,
          );

      const replyContent = data.reply ?? "No response from agent.";
      setConversationHistory((prev) => [...prev, { role: "assistant", content: replyContent }]);

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: replyContent,
        tool_calls: normalizeToolCalls(data.tool_calls),
        claims: normalizeCopilotClaims(data.claims),
        source_refs: normalizeSourceRefs(data.source_refs),
        playbook_id: data.playbook_id,
        turn_id: data.turn_id,
        answer_sections: data.answer_sections,
        claims_deterministic_support: data.claims_deterministic_support,
        tool_acknowledgment_warnings: data.tool_acknowledgment_warnings,
        judge_assessments: data.judge_assessments,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      if (repeatCount >= 2 && !repeatHintShownRef.current.has(norm)) {
        repeatHintShownRef.current.add(norm);
        const hint: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: buildRepeatSkillSuggestionPrompt(text),
          timestamp: new Date(),
          bubble: "repeat_hint",
        };
        setMessages((prev) => [...prev, hint]);
      }
    } catch (err) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Error: ${err instanceof Error ? err.message : "Failed to reach Investigation Copilot service"}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  };

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    void sendMessage(input);
  };

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700 gap-4">
        <div className="min-w-0 space-y-1">
          <PageTitle module="investigation">Investigation Copilot</PageTitle>
          <p className="text-xs text-gray-500 max-w-2xl leading-relaxed">
            AI assistant that reads <strong className="text-gray-400 font-medium">Cases</strong>,{" "}
            <strong className="text-gray-400 font-medium">Graph</strong>,{" "}
            <strong className="text-gray-400 font-medium">decision audits</strong>,{" "}
            <strong className="text-gray-400 font-medium">platform audit</strong> (recent admin/user actions), lists,
            velocity signals, and <strong className="text-gray-400 font-medium">uploaded batch files</strong> (CSV, JSON,
            Excel) to summarize and suggest next steps—it does{" "}
            <strong className="text-gray-400 font-medium">not</strong> change
            production rules or decisions by itself. Use <strong className="text-gray-400 font-medium">preset skills</strong>{" "}
            below for one-tap workflows (⚡ runs immediately) or to pre-fill longer prompts you can edit. Type{" "}
            <code className="text-gray-400">/skill</code> in the box anytime for the full catalog (ids + labels) or{" "}
            <code className="text-gray-400">/skill &lt;id&gt;</code> for one prompt.
          </p>
          <p className="text-[11px] text-gray-600">
            {contextCaseId
              ? `Case context: ${contextCaseId.slice(0, 8)}… · tenant ${contextTenantId}`
              : conversationHistory.length > 0
                ? `${conversationHistory.length} messages in this chat`
                : "No case linked — open from a case to pre-load context"}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <input
              ref={batchFileRef}
              type="file"
              accept=".csv,.json,.ndjson,.xlsx,text/csv,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="hidden"
              onChange={(ev) => void handleBatchFileSelected(ev)}
            />
            <button
              type="button"
              disabled={batchUploadBusy || sending}
              onClick={() => batchFileRef.current?.click()}
              className="text-[11px] px-2.5 py-1 rounded-md bg-surface-700 hover:bg-surface-600 text-gray-300 disabled:opacity-50"
            >
              {batchUploadBusy ? "Uploading…" : "Upload batch (CSV / JSON / Excel)"}
            </button>
            {activeBatch && (
              <>
                <span className="text-[11px] text-gray-500 truncate max-w-[220px]" title={activeBatch.batchId}>
                  {activeBatch.filename} · {activeBatch.rowCount} rows · {activeBatch.columnCount} cols
                </span>
                <button
                  type="button"
                  onClick={() => setActiveBatch(null)}
                  className="text-[11px] text-amber-400/90 hover:text-amber-300"
                >
                  Clear batch
                </button>
              </>
            )}
            <label className="flex items-center gap-2 text-[11px] text-gray-500">
              <input
                type="checkbox"
                className="rounded border-surface-600"
                checked={useStreamReply}
                onChange={(e) => setUseStreamReply(e.target.checked)}
              />
              <span>Stream reply (SSE)</span>
            </label>
            <label className="flex flex-wrap items-center gap-2 text-[11px] text-gray-500 min-w-0">
              <span className="shrink-0 text-gray-600">Playbook</span>
              <select
                className="bg-surface-800 border border-surface-600 rounded-md px-2 py-1 text-gray-300 max-w-[min(240px,100%)]"
                value={selectedPlaybookId}
                onChange={(e) => setSelectedPlaybookId(e.target.value)}
                disabled={sending}
                title="Sends playbook_id with each message; server appends typology workflow hints (GET /v1/playbooks)."
              >
                <option value="">None (generic)</option>
                {playbooks.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-col gap-1 min-w-0 w-full max-w-md">
              <span className="text-[10px] text-gray-600 uppercase tracking-wide">Investigation memo (search_knowledge)</span>
              <div className="flex flex-wrap gap-1.5 items-center">
                <input
                  type="text"
                  placeholder="Title"
                  value={memoTitle}
                  onChange={(e) => setMemoTitle(e.target.value)}
                  disabled={memoBusy || sending}
                  className="flex-1 min-w-[100px] bg-surface-800 border border-surface-600 rounded px-2 py-1 text-[11px] text-gray-300"
                />
                <button
                  type="button"
                  disabled={memoBusy || sending || !memoBody.trim()}
                  onClick={() => void handleMemoSave()}
                  className="text-[11px] px-2 py-1 rounded-md bg-surface-700 hover:bg-surface-600 text-gray-300 disabled:opacity-50"
                >
                  {memoBusy ? "Saving…" : "Save memo"}
                </button>
              </div>
              <textarea
                value={memoBody}
                onChange={(e) => setMemoBody(e.target.value)}
                disabled={memoBusy || sending}
                placeholder="Paste runbook excerpt, policy note, or investigation context…"
                rows={2}
                className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-[11px] text-gray-300 resize-y min-h-[2.5rem]"
              />
            </div>

            <details className="w-full max-w-2xl rounded-lg border border-surface-700/90 bg-surface-900/50 group/fban">
              <summary className="cursor-pointer select-none px-2.5 py-2 text-[11px] text-gray-400 hover:text-gray-300 list-none flex flex-wrap items-center gap-2">
                <span className="text-brand-400/90 group-open/fban:rotate-90 transition-transform inline-block">▸</span>
                <span className="font-medium text-gray-300">Feedback analytics</span>
                <span className="text-gray-600">
                  tenant <span className="font-mono text-gray-500">{contextTenantId}</span>
                </span>
                {feedbackSummary != null && feedbackSummary.total > 0 && (
                  <span className="text-gray-500">
                    · {feedbackSummary.total} in last {feedbackSummary.window_days}d
                    {feedbackSummary.avg_rating != null && (
                      <> · avg {feedbackSummary.avg_rating > 0 ? "+" : ""}
                      {feedbackSummary.avg_rating}</>
                    )}
                  </span>
                )}
              </summary>
              <div className="px-2.5 pb-2.5 pt-0 space-y-2 border-t border-surface-700/70">
                <div className="flex flex-wrap items-center gap-2 pt-2">
                  <label className="flex items-center gap-1.5 text-[10px] text-gray-500">
                    <span className="text-gray-600">Window</span>
                    <select
                      className="bg-surface-800 border border-surface-600 rounded px-1.5 py-0.5 text-gray-300"
                      value={feedbackWindowDays}
                      onChange={(e) => setFeedbackWindowDays(Number(e.target.value))}
                      disabled={feedbackAnalyticsLoading}
                    >
                      <option value={7}>7 days</option>
                      <option value={30}>30 days</option>
                      <option value={90}>90 days</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={feedbackAnalyticsLoading}
                    onClick={() => void loadFeedbackAnalytics()}
                    className="text-[10px] px-2 py-0.5 rounded-md bg-surface-700 hover:bg-surface-600 text-gray-300 disabled:opacity-50"
                  >
                    {feedbackAnalyticsLoading ? "Loading…" : "Refresh"}
                  </button>
                </div>
                {feedbackAnalyticsError && (
                  <p className="text-[10px] text-rose-400/90">{feedbackAnalyticsError}</p>
                )}
                {feedbackSummary && !feedbackAnalyticsError && (
                  <div className="space-y-1.5">
                    {feedbackSummary.total === 0 ? (
                      <p className="text-[10px] text-gray-600">
                        No ratings in this window. Use <span className="text-gray-400">Helpful</span> /{" "}
                        <span className="text-gray-400">Not helpful</span> on assistant turns.
                      </p>
                    ) : (
                      <>
                        <div className="flex h-2 rounded overflow-hidden bg-surface-800 border border-surface-700/80 max-w-md">
                          {(() => {
                            const down = feedbackSummary.by_rating["-1"] ?? 0;
                            const neu = feedbackSummary.by_rating["0"] ?? 0;
                            const up = feedbackSummary.by_rating["1"] ?? 0;
                            const t = Math.max(1, down + neu + up);
                            return (
                              <>
                                <div
                                  className="bg-rose-500/70 h-full"
                                  style={{ width: `${(down / t) * 100}%` }}
                                  title={`Not helpful: ${down}`}
                                />
                                <div
                                  className="bg-gray-500/50 h-full"
                                  style={{ width: `${(neu / t) * 100}%` }}
                                  title={`Neutral: ${neu}`}
                                />
                                <div
                                  className="bg-emerald-500/70 h-full"
                                  style={{ width: `${(up / t) * 100}%` }}
                                  title={`Helpful: ${up}`}
                                />
                              </>
                            );
                          })()}
                        </div>
                        <div className="flex flex-wrap gap-3 text-[10px] text-gray-500">
                          <span>
                            <span className="text-rose-400/90">▼</span> {feedbackSummary.by_rating["-1"] ?? 0} not helpful
                          </span>
                          <span>
                            <span className="text-gray-500">◆</span> {feedbackSummary.by_rating["0"] ?? 0} neutral
                          </span>
                          <span>
                            <span className="text-emerald-400/90">▲</span> {feedbackSummary.by_rating["1"] ?? 0} helpful
                          </span>
                        </div>
                      </>
                    )}
                  </div>
                )}
                {feedbackRecent.length > 0 && (
                  <div className="rounded-md border border-surface-700/60 overflow-hidden max-h-40 overflow-y-auto">
                    <table className="w-full text-[10px] text-left">
                      <thead className="sticky top-0 bg-surface-900 text-gray-600 uppercase tracking-wide">
                        <tr>
                          <th className="px-2 py-1 font-medium">When</th>
                          <th className="px-2 py-1 font-medium">Rating</th>
                          <th className="px-2 py-1 font-medium">Analyst</th>
                          <th className="px-2 py-1 font-medium">Turn</th>
                        </tr>
                      </thead>
                      <tbody className="text-gray-400 divide-y divide-surface-700/50">
                        {feedbackRecent.map((row) => (
                          <tr key={row.id} className="bg-surface-900/40">
                            <td className="px-2 py-1 whitespace-nowrap">
                              {new Date(row.created_at * 1000).toLocaleString(undefined, {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </td>
                            <td className="px-2 py-1">
                              {row.rating === 1 ? (
                                <span className="text-emerald-400/90">+1</span>
                              ) : row.rating === -1 ? (
                                <span className="text-rose-400/90">−1</span>
                              ) : (
                                <span className="text-gray-500">0</span>
                              )}
                            </td>
                            <td className="px-2 py-1 font-mono truncate max-w-[100px]" title={row.analyst_id}>
                              {row.analyst_id}
                            </td>
                            <td className="px-2 py-1 font-mono truncate max-w-[120px]" title={row.turn_id}>
                              {row.turn_id.length > 12 ? `${row.turn_id.slice(0, 10)}…` : row.turn_id}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </details>
          </div>
        </div>
        <button
          type="button"
          onClick={handleNewSession}
          className="shrink-0 px-4 py-2 bg-surface-700 hover:bg-surface-600 text-gray-300 text-sm font-medium rounded-lg transition-colors"
        >
          Clear chat
        </button>
      </div>

      {(governanceInfo || (viteGovProfile && viteGovLabels[viteGovProfile])) && (
        <div className="px-6 py-2 border-b border-surface-700/90 bg-surface-900/60 text-[11px] text-gray-500 leading-relaxed">
          <span className="text-gray-400 font-medium">AI governance build:</span>{" "}
          {governanceInfo?.label ?? viteGovLabels[viteGovProfile ?? ""] ?? viteGovProfile}
          {governanceInfo?.batch_ttl_seconds != null && (
            <span className="text-gray-600"> · batch upload TTL {Math.round(governanceInfo.batch_ttl_seconds / 60)} min</span>
          )}
          <span className="text-gray-600"> — copilot uses regional system rules; not legal advice.</span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="max-w-4xl mx-auto py-4 space-y-8">
            <div className="flex flex-col sm:flex-row gap-4 sm:items-start">
              <ModuleIcon module="investigation" className="w-14 h-14 text-gray-600 shrink-0 hidden sm:block" aria-hidden />
              <div className="space-y-2 min-w-0">
                <h2 className="text-lg font-semibold text-gray-300">Preset skills & workflows</h2>
                <p className="text-sm text-gray-500 leading-relaxed">
                  Skills bundle prompts the agent uses like playbooks: case + rule reviews, batch thinking, experiment
                  readouts, monitoring reports, and analyst shortcuts. <span className="text-amber-400/90">⚡ Instant</span>{" "}
                  sends in one click for fast answers; others fill the composer so you can tweak dates, segments, or
                  tenant scope before sending. Use <code className="text-gray-400">/skill</code> for the full skill list
                  in chat.
                </p>
              </div>
            </div>

            {QUICK_INSTANT_SKILLS.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-brand-400/90">Quick run — instant</h3>
                <div className="flex flex-wrap gap-2">
                  {QUICK_INSTANT_SKILLS.map((skill) => (
                    <SkillChip
                      key={skill.id}
                      label={skill.label}
                      instant
                      disabled={sending}
                      onTrigger={() => void sendMessage(skill.prompt)}
                    />
                  ))}
                </div>
              </section>
            )}

            <div className="space-y-6">
              {COPILOT_SKILL_GROUPS.map((group) => (
                <section key={group.id} className="rounded-xl border border-surface-700/80 bg-surface-900/40 p-4 space-y-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-200">{group.title}</h3>
                    {group.blurb && <p className="text-xs text-gray-500 mt-1 leading-relaxed">{group.blurb}</p>}
                  </div>
                  <ul className="flex flex-col gap-2">
                    {group.skills.map((skill) => (
                      <li key={skill.id} className="flex flex-wrap items-center gap-2">
                        <SkillChip
                          label={skill.label}
                          instant={skill.instant === true}
                          disabled={sending}
                          onTrigger={() =>
                            skill.instant ? void sendMessage(skill.prompt) : setInput(skill.prompt)
                          }
                        />
                        {skill.instant ? (
                          <span className="text-[10px] text-gray-600">instant</span>
                        ) : (
                          <span className="text-[10px] text-gray-600">fills composer</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            tenantId={contextTenantId}
            analystId={DEFAULT_ANALYST}
            onFeedbackRecorded={() => void loadFeedbackAnalytics()}
          />
        ))}

        {sending && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-brand-600/20 flex items-center justify-center flex-shrink-0">
              <span className="text-brand-400 text-xs font-semibold">AI</span>
            </div>
            <div className="bg-surface-800 rounded-xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" />
                <span
                  className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: "0.15s" }}
                />
                <span
                  className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: "0.3s" }}
                />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="px-6 py-4 border-t border-surface-700 space-y-3">
        <fieldset
          disabled={sending}
          className="rounded-lg border border-surface-700 bg-surface-900/40 px-3 py-2.5 space-y-2"
        >
          <legend className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 px-1">
            Platform audit context
          </legend>
          <p className="text-[11px] text-gray-600 leading-snug -mt-0.5">
            These options change what <span className="text-gray-500">admin audit</span> data is sent with each message.
            Case/graph tools are unchanged. The server re-checks flags so tampered requests cannot re-enable audit when it
            is turned off here.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-start">
            <label className="flex gap-2 items-start cursor-pointer text-xs text-gray-400 max-w-md">
              <input
                type="checkbox"
                className="mt-0.5 rounded border-surface-600"
                checked={trackHistoricalActions}
                onChange={(e) => setTrackHistoricalActions(e.target.checked)}
              />
              <span>
                <span className="text-gray-300 font-medium">Track historical actions</span>
                <span className="block text-[11px] text-gray-600 mt-0.5">
                  Sends recent platform audit events (who viewed/changed what). Off = minimal privacy: no audit slice in
                  the prompt; answers rely on case tools and your message only.
                </span>
              </span>
            </label>
            <label className="flex gap-2 items-start cursor-pointer text-xs text-gray-400 max-w-md">
              <input
                type="checkbox"
                className="mt-0.5 rounded border-surface-600"
                disabled={!trackHistoricalActions}
                checked={onlySessionAudit}
                onChange={(e) => setOnlySessionAudit(e.target.checked)}
              />
              <span>
                <span className="text-gray-300 font-medium">Only this session</span>
                <span className="block text-[11px] text-gray-600 mt-0.5">
                  Audit rows are limited to activity since you opened this chat (or pressed Clear chat). Narrows context to
                  current work; older tenant activity is omitted.
                </span>
              </span>
            </label>
            <label className="flex gap-2 items-start cursor-pointer text-xs text-gray-400 max-w-md">
              <input
                type="checkbox"
                className="mt-0.5 rounded border-surface-600"
                disabled={!trackHistoricalActions}
                checked={skipSessionActions}
                onChange={(e) => setSkipSessionActions(e.target.checked)}
              />
              <span>
                <span className="text-gray-300 font-medium">Skip session / copilot noise</span>
                <span className="block text-[11px] text-gray-600 mt-0.5">
                  Removes Investigation Copilot usage rows and generic session/auth audit noise so the model focuses on
                  substantive product actions (cases, rules, graph, admin changes).
                </span>
              </span>
            </label>
          </div>
        </fieldset>
        {messages.length > 0 && (
          <details className="group rounded-lg border border-surface-700 bg-surface-900/50 text-sm">
            <summary className="cursor-pointer select-none px-3 py-2 text-gray-400 hover:text-gray-300 list-none flex items-center gap-2">
              <span className="text-brand-400/90 group-open:rotate-90 transition-transform inline-block">▸</span>
              More preset skills — or type <code className="text-gray-500">/skill</code> in the box
            </summary>
            <div className="px-3 pb-3 pt-1 space-y-4 max-h-48 overflow-y-auto border-t border-surface-700/80">
              <div className="flex flex-wrap gap-1.5">
                {QUICK_INSTANT_SKILLS.map((skill) => (
                  <SkillChip
                    key={`q-${skill.id}`}
                    label={skill.label}
                    instant
                    compact
                    disabled={sending}
                    onTrigger={() => void sendMessage(skill.prompt)}
                  />
                ))}
              </div>
              {COPILOT_SKILL_GROUPS.map((group) => (
                <div key={`chat-${group.id}`}>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-600 mb-1.5">{group.title}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {group.skills.map((skill) => (
                      <SkillChip
                        key={`chat-${skill.id}`}
                        label={skill.label}
                        instant={skill.instant === true}
                        compact
                        disabled={sending}
                        onTrigger={() =>
                          skill.instant ? void sendMessage(skill.prompt) : setInput(skill.prompt)
                        }
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>
        )}
        <form onSubmit={handleSend} className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="/skill for catalog — or type a question; ⚡ presets send in one tap…"
            disabled={sending}
            className="flex-1 bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-xl px-4 py-3 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50 placeholder-gray-500"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="px-6 py-3 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

function formatBoldSegments(line: string): ReactNode {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-gray-100">
          {p.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{p}</span>;
  });
}

function RichHelpBody({ text }: { text: string }) {
  const chunks = text.split(/(```[\s\S]*?```)/g);
  return (
    <div className="space-y-2">
      {chunks.map((chunk, i) => {
        if (chunk.startsWith("```")) {
          const inner = chunk.replace(/^```[^\n]*\n?|```$/g, "").trimEnd();
          return (
            <pre
              key={i}
              className="text-xs text-gray-400 bg-surface-950 border border-surface-600 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap"
            >
              {inner}
            </pre>
          );
        }
        if (!chunk.trim()) return null;
        return (
          <div key={i} className="text-sm leading-relaxed">
            {chunk.split("\n").map((line, li) => (
              <span key={li}>
                {li > 0 ? <br /> : null}
                {formatBoldSegments(line)}
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function SkillChip({
  label,
  instant,
  compact,
  disabled,
  onTrigger,
}: {
  label: string;
  instant?: boolean;
  compact?: boolean;
  disabled?: boolean;
  onTrigger: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onTrigger}
      title={instant ? "Runs immediately" : "Fills the message box — edit then Send"}
      className={`text-left rounded-lg border transition-colors disabled:opacity-40 ${
        instant
          ? "border-brand-500/35 bg-brand-600/10 text-brand-200/95 hover:bg-brand-600/18"
          : "border-surface-600 bg-surface-800 text-gray-300 hover:bg-surface-700 hover:text-gray-200"
      } ${compact ? "px-2 py-1 text-[11px] max-w-[200px] truncate" : "px-3 py-2 text-xs max-w-full sm:max-w-xl"}`}
    >
      {label}
    </button>
  );
}

function MessageBubble({
  message,
  tenantId,
  analystId,
  onFeedbackRecorded,
}: {
  message: Message;
  tenantId: string;
  analystId: string;
  onFeedbackRecorded?: () => void;
}) {
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const isUser = message.role === "user";
  const richBubble = message.bubble === "system_help" || message.bubble === "repeat_hint";

  const assistantShell =
    message.bubble === "system_help"
      ? "border border-brand-500/30 bg-surface-900/90 text-gray-200 rounded-tl-sm"
      : message.bubble === "repeat_hint"
        ? "border border-amber-500/35 bg-amber-500/[0.07] text-gray-200 rounded-tl-sm"
        : "bg-surface-800 text-gray-200 rounded-tl-sm";

  return (
    <div className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
          isUser
            ? "bg-surface-700 text-gray-400"
            : message.bubble === "repeat_hint"
              ? "bg-amber-500/15 text-amber-400"
              : message.bubble === "system_help"
                ? "bg-brand-600/25 text-brand-300"
                : "bg-brand-600/20 text-brand-400"
        }`}
      >
        <span className="text-xs font-semibold">
          {isUser ? "U" : message.bubble === "system_help" ? "⌘" : message.bubble === "repeat_hint" ? "!" : "AI"}
        </span>
      </div>

      <div
        className={`${isUser ? "max-w-[75%]" : richBubble ? "max-w-2xl w-full" : "max-w-[75%]"} ${isUser ? "items-end" : "items-start"}`}
      >
        <div
          className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
            isUser ? "bg-brand-600 text-white rounded-tr-sm whitespace-pre-wrap" : assistantShell
          }`}
        >
          {isUser || !richBubble ? (
            <span className="whitespace-pre-wrap">{message.content}</span>
          ) : (
            <RichHelpBody text={message.content} />
          )}
        </div>

        {!richBubble && message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setToolsExpanded(!toolsExpanded)}
              className="text-xs text-gray-500 hover:text-gray-400 transition-colors flex items-center gap-1"
            >
              <span className={`transition-transform ${toolsExpanded ? "rotate-90" : ""}`}>▶</span>
              Copilot steps (tool calls): {message.tool_calls.length}
            </button>
            {toolsExpanded && (
              <div className="mt-1.5 space-y-1.5 animate-fade-in">
                {message.tool_calls.map((tc, i) => (
                  <div
                    key={i}
                    className="bg-surface-900 border border-surface-700 rounded-lg p-3 text-xs"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-brand-400 font-medium">
                        {tc.name}
                      </span>
                    </div>
                    <pre className="text-gray-500 overflow-x-auto whitespace-pre-wrap break-all">
                      {tc.arguments}
                    </pre>
                    {tc.result && (
                      <pre className="text-gray-400 mt-1.5 pt-1.5 border-t border-surface-700 overflow-x-auto whitespace-pre-wrap break-all">
                        {tc.result}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!isUser && !richBubble && message.playbook_id && (
          <div className="mt-2 text-[10px] text-gray-600">
            Active playbook: <span className="text-gray-400 font-mono">{message.playbook_id}</span>
          </div>
        )}

        {!isUser && !richBubble && message.tool_acknowledgment_warnings && message.tool_acknowledgment_warnings.length > 0 && (
          <div className="mt-2 text-[11px] text-amber-400/95 border border-amber-500/35 rounded-md px-2 py-1.5 max-w-[75vw] sm:max-w-xl">
            <div className="font-medium text-amber-200/90 mb-0.5">Tool failures may be under-acknowledged in prose</div>
            <ul className="list-disc pl-4 text-amber-400/85 space-y-0.5">
              {message.tool_acknowledgment_warnings.map((w, i) => (
                <li key={i} className="break-words">
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}

        {!isUser && !richBubble && message.answer_sections && (message.answer_sections.sections_found?.length ?? 0) > 0 && (
          <details className="mt-2 text-xs border-t border-surface-700/80 pt-2 max-w-[75vw] sm:max-w-xl">
            <summary className="cursor-pointer text-gray-500 hover:text-gray-400 select-none">Structured sections (parsed)</summary>
            <div className="mt-2 space-y-2 text-gray-400">
              {message.answer_sections.facts_from_tools && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-500 uppercase">Facts from tools</div>
                  <pre className="whitespace-pre-wrap text-[11px] mt-0.5">{message.answer_sections.facts_from_tools}</pre>
                </div>
              )}
              {message.answer_sections.inferences && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-500 uppercase">Inferences</div>
                  <pre className="whitespace-pre-wrap text-[11px] mt-0.5">{message.answer_sections.inferences}</pre>
                </div>
              )}
              {message.answer_sections.unknowns && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-500 uppercase">Unknowns</div>
                  <pre className="whitespace-pre-wrap text-[11px] mt-0.5">{message.answer_sections.unknowns}</pre>
                </div>
              )}
              {message.answer_sections.next_steps && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-500 uppercase">Next steps</div>
                  <pre className="whitespace-pre-wrap text-[11px] mt-0.5">{message.answer_sections.next_steps}</pre>
                </div>
              )}
            </div>
          </details>
        )}

        {!isUser && !richBubble && message.claims_deterministic_support && message.claims_deterministic_support.length > 0 && (
          <details className="mt-2 text-[11px] border-t border-surface-700/80 pt-2 max-w-[75vw] sm:max-w-xl">
            <summary className="cursor-pointer text-gray-500 hover:text-gray-400 select-none">
              Claim token overlap vs tools (heuristic)
            </summary>
            <ul className="mt-1.5 space-y-1 text-gray-400 font-mono text-[10px]">
              {message.claims_deterministic_support.map((row) => (
                <li key={row.claim_index}>
                  #{row.claim_index} {row.supported ? "overlap" : "no_overlap"} ({row.method})
                </li>
              ))}
            </ul>
          </details>
        )}

        {!isUser && !richBubble && message.judge_assessments != null && (
          <details className="mt-2 text-[11px] border-t border-surface-700/80 pt-2 max-w-[75vw] sm:max-w-xl">
            <summary className="cursor-pointer text-gray-500 hover:text-gray-400 select-none">Judge pass (optional)</summary>
            <pre className="mt-1 text-gray-500 overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(message.judge_assessments, null, 2)}
            </pre>
          </details>
        )}

        {!isUser && !richBubble && message.turn_id && (
          <div className="mt-2 flex flex-wrap gap-2 items-center text-[11px] text-gray-500">
            <span className="text-gray-600">Turn feedback</span>
            <button
              type="button"
              disabled={feedbackBusy}
              className="px-2 py-0.5 rounded bg-surface-700 hover:bg-surface-600 text-gray-300 disabled:opacity-50"
              onClick={() => {
                setFeedbackBusy(true);
                void investigation
                  .submitFeedback({
                    turn_id: message.turn_id!,
                    rating: 1,
                    tenant_id: tenantId,
                    analyst_id: analystId,
                  })
                  .then(() => onFeedbackRecorded?.())
                  .finally(() => setFeedbackBusy(false));
              }}
            >
              Helpful
            </button>
            <button
              type="button"
              disabled={feedbackBusy}
              className="px-2 py-0.5 rounded bg-surface-700 hover:bg-surface-600 text-gray-300 disabled:opacity-50"
              onClick={() => {
                setFeedbackBusy(true);
                void investigation
                  .submitFeedback({
                    turn_id: message.turn_id!,
                    rating: -1,
                    tenant_id: tenantId,
                    analyst_id: analystId,
                  })
                  .then(() => onFeedbackRecorded?.())
                  .finally(() => setFeedbackBusy(false));
              }}
            >
              Not helpful
            </button>
          </div>
        )}

        {!isUser && !richBubble && message.source_refs && message.source_refs.length > 0 && (
          <div className="mt-2 text-xs border-t border-surface-700/80 pt-2 max-w-[75vw] sm:max-w-xl">
            <div className="text-gray-500 font-medium mb-1">Source references (tool touches)</div>
            <ul className="space-y-1.5 text-gray-400">
              {message.source_refs.map((s, i) => (
                <li key={i} className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline text-[11px]">
                  <span className={s.ok ? "text-emerald-500/90 font-mono uppercase shrink-0" : "text-rose-400/90 font-mono uppercase shrink-0"}>
                    {s.ok ? "ok" : "err"}
                  </span>
                  <span className="text-brand-400/90 font-medium shrink-0">{s.tool}</span>
                  {[s.case_id, s.entity_id, s.trace_id, s.batch_id]
                    .filter((id): id is string => Boolean(id))
                    .map((id, j) => (
                      <span
                        key={`${i}-${j}-${id}`}
                        className="text-gray-500 font-mono text-[10px] truncate max-w-[160px]"
                        title={id}
                      >
                        {id}
                      </span>
                    ))}
                  {s.error ? <span className="text-rose-400/80 text-[10px]">{s.error}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        )}

        {!isUser && !richBubble && message.claims && message.claims.length > 0 && (
          <div className="mt-2 text-xs border-t border-surface-700/80 pt-2 max-w-[75vw] sm:max-w-xl">
            <div className="text-gray-500 font-medium mb-1">Claims (source)</div>
            <ul className="space-y-1.5 text-gray-400">
              {message.claims.map((c, i) => (
                <li key={i} className="flex gap-2 items-start">
                  <span
                    className={
                      c.source === "tool"
                        ? "shrink-0 text-emerald-500/90 font-mono text-[10px] uppercase"
                        : "shrink-0 text-gray-600 font-mono text-[10px] uppercase"
                    }
                  >
                    {c.source}
                  </span>
                  <span className="whitespace-pre-wrap break-words">{c.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <span className="text-[10px] text-gray-600 mt-1 block">
          {message.timestamp.toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}
