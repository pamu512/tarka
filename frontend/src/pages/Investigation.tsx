import { useState, useRef, useEffect } from "react";
import { investigation } from "../api/client";

interface ToolCall {
  name: string;
  arguments: string;
  result?: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCall[];
  timestamp: Date;
}

export default function Investigation() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationHistory, setConversationHistory] = useState<{ role: string; content: string }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleNewSession = () => {
    setMessages([]);
    setConversationHistory([]);
    setInput("");
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

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

    try {
      const data = await investigation.chatWithHistory(updatedHistory);

      const replyContent = data.reply ?? "No response from agent.";
      setConversationHistory((prev) => [...prev, { role: "assistant", content: replyContent }]);

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: replyContent,
        tool_calls: (data.tool_calls as ToolCall[] | undefined) ?? [],
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Error: ${err instanceof Error ? err.message : "Failed to reach investigation agent"}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700">
        <div>
          <h1 className="text-lg font-bold text-gray-100">
            AI Investigation Agent
          </h1>
          <p className="text-xs text-gray-500">
            {conversationHistory.length > 0
              ? `${conversationHistory.length} messages in context`
              : "Start a new investigation"}
          </p>
        </div>
        <button
          onClick={handleNewSession}
          className="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-gray-300 text-sm font-medium rounded-lg transition-colors"
        >
          New Investigation
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center space-y-3">
              <div className="text-5xl text-gray-700">\u2315</div>
              <h2 className="text-lg font-semibold text-gray-400">
                Investigation Agent
              </h2>
              <p className="text-sm text-gray-500 max-w-md">
                Ask questions about entities, transactions, or fraud patterns.
                The agent can query decision logs, graph data, and analytics to
                help you investigate suspicious activity.
              </p>
              <div className="flex flex-wrap gap-2 justify-center pt-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setInput(s)}
                    className="px-3 py-1.5 bg-surface-800 border border-surface-700 text-gray-400 text-xs rounded-lg hover:bg-surface-700 hover:text-gray-300 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {sending && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-brand-600/20 flex items-center justify-center flex-shrink-0">
              <span className="text-brand-400 text-sm">\u2315</span>
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
      <div className="px-6 py-4 border-t border-surface-700">
        <form onSubmit={handleSend} className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the investigation agent..."
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

const SUGGESTIONS = [
  "Investigate entity user-123",
  "Show recent high-risk decisions",
  "Find fraud rings for tenant-1",
  "Analyze transaction patterns",
];

function MessageBubble({ message }: { message: Message }) {
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const isUser = message.role === "user";

  return (
    <div className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
          isUser
            ? "bg-surface-700 text-gray-400"
            : "bg-brand-600/20 text-brand-400"
        }`}
      >
        <span className="text-sm">{isUser ? "U" : "\u2315"}</span>
      </div>

      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`rounded-xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? "bg-brand-600 text-white rounded-tr-sm"
              : "bg-surface-800 text-gray-200 rounded-tl-sm"
          }`}
        >
          {message.content}
        </div>

        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setToolsExpanded(!toolsExpanded)}
              className="text-xs text-gray-500 hover:text-gray-400 transition-colors flex items-center gap-1"
            >
              <span className={`transition-transform ${toolsExpanded ? "rotate-90" : ""}`}>
                \u25B6
              </span>
              {message.tool_calls.length} tool call
              {message.tool_calls.length > 1 ? "s" : ""}
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

        <span className="text-[10px] text-gray-600 mt-1 block">
          {message.timestamp.toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}
