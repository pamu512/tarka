import { useCallback, useMemo, useState, type ReactElement } from "react";

import type { GlobalErrorTrace } from "@/errors/buildErrorTrace";
import { sanitizeErrorPayloadForDisplay } from "@/errors/sanitizeErrorPayload";

export interface GlobalErrorFallbackProps {
  trace: GlobalErrorTrace;
  onRetry: () => void;
}

function formatDisplayPayload(trace: GlobalErrorTrace): Record<string, unknown> {
  return {
    source: trace.source,
    capturedAt: trace.capturedAt,
    summary: trace.summary,
    react: trace.react ?? null,
    componentStack: trace.componentStack ?? null,
    http: {
      status: trace.httpStatus ?? null,
      url: trace.httpUrl ?? null,
      /** FastAPI-style JSON body when present (sanitized before render). */
      responseJson: trace.httpResponseJson ?? null,
    },
    raw: trace.raw ?? null,
  };
}

export function GlobalErrorFallback({ trace, onRetry }: GlobalErrorFallbackProps): ReactElement {
  const [copyHint, setCopyHint] = useState<string | null>(null);

  const { displayJson, copyText } = useMemo(() => {
    const payload = formatDisplayPayload(trace);
    const sanitized = sanitizeErrorPayloadForDisplay(payload) as Record<string, unknown>;
    const text = `${JSON.stringify(sanitized, null, 2)}\n`;
    return { displayJson: sanitized, copyText: text };
  }, [trace]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(copyText);
      setCopyHint("Copied trace to clipboard.");
      window.setTimeout(() => setCopyHint(null), 4000);
    } catch {
      setCopyHint("Clipboard unavailable — select the trace text manually.");
      window.setTimeout(() => setCopyHint(null), 6000);
    }
  }, [copyText]);

  return (
    <div className="min-h-screen bg-surface-950 text-gray-100 flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-3xl space-y-4">
        <header className="space-y-1">
          <h1 className="text-xl font-semibold text-red-300">Application error</h1>
          <p className="text-sm text-gray-400">
            Something went wrong in the Tarka UI. The technical trace below may include a FastAPI{" "}
            <code className="text-gray-300">detail</code> / <code className="text-gray-300">error</code> payload when a
            network call failed. Secrets and tokens are redacted before display.
          </p>
          <p className="text-sm text-gray-300 font-medium">{trace.summary}</p>
        </header>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center justify-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 transition-colors"
          >
            Copy trace
          </button>
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center justify-center rounded-md border border-surface-600 bg-surface-800 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-surface-700 transition-colors"
          >
            Try again
          </button>
        </div>
        {copyHint ? <p className="text-xs text-amber-300/90">{copyHint}</p> : null}

        <section aria-label="Error trace JSON" className="rounded-lg border border-red-500/30 bg-black/40 overflow-hidden">
          <pre className="max-h-[min(60vh,32rem)] overflow-auto p-4 text-xs leading-relaxed text-gray-200 font-mono whitespace-pre-wrap break-words">
            {JSON.stringify(displayJson, null, 2)}
          </pre>
        </section>
      </div>
    </div>
  );
}
