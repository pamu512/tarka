"use client";

import { useCallback, useState } from "react";
import { useSWRConfig } from "swr";
import { Crosshair } from "lucide-react";
import { getAuditRecentUrl } from "@/lib/audit-recent-url";
import { getSimulateAttackUrl } from "@/lib/demo-simulate-url";
import type { AuditRecentItem, AuditRecentResponse } from "@/types/audit-recent";

const PATTERNS_TOTAL = 5;

type NdjsonPayload = {
  pattern_index: number;
  total: number;
  item: AuditRecentItem;
};

function prependAuditItem(
  prev: AuditRecentResponse | undefined,
  item: AuditRecentItem,
): AuditRecentResponse {
  const rest = (prev?.items ?? []).filter((r) => r.transaction_id !== item.transaction_id);
  return { items: [item, ...rest].slice(0, 16) };
}

function isNdjsonStream(contentType: string): boolean {
  const ct = contentType.toLowerCase();
  return ct.includes("ndjson") || ct.includes("newline-delimited");
}

async function consumeNdjsonStream(
  res: Response,
  onRow: (payload: NdjsonPayload) => void,
): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("Simulate attack response has no body stream");
  }
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const payload = JSON.parse(trimmed) as NdjsonPayload;
        onRow(payload);
      } catch {
        throw new Error("Invalid NDJSON line from simulate_attack stream");
      }
    }
  }

  const tail = buffer.trim();
  if (tail) {
    try {
      const payload = JSON.parse(tail) as NdjsonPayload;
      onRow(payload);
    } catch {
      throw new Error("Invalid trailing NDJSON from simulate_attack stream");
    }
  }
}

function extractItemsFromJson(body: unknown): AuditRecentItem[] {
  if (!body || typeof body !== "object") return [];
  const o = body as Record<string, unknown>;
  const raw = o.items ?? o.outcomes ?? o.results;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (x): x is AuditRecentItem =>
      x !== null &&
      typeof x === "object" &&
      typeof (x as AuditRecentItem).transaction_id === "string",
  );
}

export function GlobalHeader() {
  const { mutate } = useSWRConfig();
  const [pending, setPending] = useState(false);
  const [patternsDone, setPatternsDone] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const auditUrl = getAuditRecentUrl();

  const runSimulateAttack = useCallback(async () => {
    setErrorMessage(null);
    setPending(true);
    setPatternsDone(0);

    const url = getSimulateAttackUrl();

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson, application/json" },
        body: "{}",
        cache: "no-store",
      });

      if (!res.ok) {
        throw new Error(`Simulate attack failed (${res.status})`);
      }

      const contentType = res.headers.get("content-type") ?? "";

      if (isNdjsonStream(contentType)) {
        await consumeNdjsonStream(res, (payload) => {
          setPatternsDone(Math.min(PATTERNS_TOTAL, payload.pattern_index + 1));
          mutate(
            auditUrl,
            (prev) => prependAuditItem(prev, payload.item),
            { revalidate: false },
          );
        });
      } else {
        const json: unknown = await res.json();
        const items = extractItemsFromJson(json).slice(0, PATTERNS_TOTAL);
        if (items.length === 0) {
          throw new Error("Orchestrator returned no attack outcomes");
        }
        for (let i = 0; i < items.length; i++) {
          setPatternsDone(i + 1);
          mutate(auditUrl, (prev) => prependAuditItem(prev, items[i]), {
            revalidate: false,
          });
          await new Promise<void>((r) => setTimeout(r, 160));
        }
      }

      await mutate(auditUrl);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Simulate attack request error";
      setErrorMessage(msg);
    } finally {
      setPending(false);
      setPatternsDone(0);
    }
  }, [auditUrl, mutate]);

  const progressFraction = pending ? Math.min(1, patternsDone / PATTERNS_TOTAL) : 0;

  return (
    <header className="flex w-full shrink-0 flex-col gap-2 border-b border-slate-800 bg-slate-950 px-4 py-2">
      <div className="flex min-h-9 items-center justify-between gap-4">
        <div className="min-w-0 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
          Forensic console
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <button
            type="button"
            disabled={pending}
            aria-busy={pending}
            onClick={runSimulateAttack}
            className="inline-flex items-center gap-2 rounded-md border border-purple-700/80 bg-purple-950/50 px-3 py-1.5 text-xs font-semibold text-purple-100 transition-colors hover:bg-purple-900/60 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Crosshair className="size-3.5 shrink-0" aria-hidden strokeWidth={2} />
            {pending ? "Simulating…" : "Simulate Attack"}
          </button>
        </div>
      </div>

      {pending ? (
        <div className="flex flex-col gap-1.5 pb-1" aria-live="polite">
          <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wide text-slate-500">
            <span>Simulated patterns</span>
            <span className="tabular-nums text-slate-400">
              {patternsDone}/{PATTERNS_TOTAL}
            </span>
          </div>
          <div
            className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={PATTERNS_TOTAL}
            aria-valuenow={patternsDone}
            aria-label="Simulated attack patterns processed"
          >
            <div
              className="h-full rounded-full bg-purple-500 transition-[width] duration-300 ease-out"
              style={{ width: `${Math.min(1, progressFraction) * 100}%` }}
            />
          </div>
        </div>
      ) : null}

      {errorMessage ? (
        <p className="text-[11px] text-red-400" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </header>
  );
}
