"use client";

import { useCallback, useId, useMemo, useState } from "react";
import { Braces, FlaskConical, Plus, Trash2 } from "lucide-react";
import {
  PHASE3_OPERATORS,
  TRANSACTION_FIELD_LABELS,
  TRANSACTION_SCHEMA_FIELDS,
  type ConditionBlock,
  compileBlocksToRootNode,
} from "@/lib/compile-rule-ast";
import type { RuleShadowTestResponse } from "@/types/rule-shadow-test";

const RULE_TEST_ACTIONS = ["BLOCK", "FLAG", "SHADOW_REVIEW", "ALLOW"] as const;

function newBlock(): ConditionBlock {
  return {
    id: crypto.randomUUID(),
    field: "amount",
    operator: "GT",
    valueRaw: "",
  };
}

export type RuleBuilderProps = {
  /** Optional initial blocks (defaults to one empty row). */
  initialBlocks?: ConditionBlock[];
};

export function RuleBuilder({ initialBlocks }: RuleBuilderProps) {
  const baseId = useId();
  const [blocks, setBlocks] = useState<ConditionBlock[]>(() =>
    initialBlocks?.length ? initialBlocks.map((b) => ({ ...b, id: b.id || crypto.randomUUID() })) : [newBlock()],
  );
  const [preview, setPreview] = useState<string | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [testAction, setTestAction] = useState<string>("BLOCK");
  const [shadowResult, setShadowResult] = useState<RuleShadowTestResponse | null>(null);
  const [shadowBusy, setShadowBusy] = useState(false);
  const [shadowError, setShadowError] = useState<string | null>(null);

  const canRemove = blocks.length > 1;

  const updateBlock = useCallback((id: string, patch: Partial<ConditionBlock>) => {
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, ...patch } : b)));
  }, []);

  const addBlock = useCallback(() => {
    setBlocks((prev) => [...prev, newBlock()]);
  }, []);

  const removeBlock = useCallback(
    (id: string) => {
      if (!canRemove) return;
      setBlocks((prev) => prev.filter((b) => b.id !== id));
    },
    [canRemove],
  );

  const handlePreview = useCallback(() => {
    const out = compileBlocksToRootNode(blocks);
    if (!out.ok) {
      setCompileError(out.message);
      setPreview(null);
      return;
    }
    setCompileError(null);
    setPreview(JSON.stringify(out.root, null, 2));
  }, [blocks]);

  const handleShadowTest = useCallback(async () => {
    const out = compileBlocksToRootNode(blocks);
    if (!out.ok) {
      setCompileError(out.message);
      setShadowResult(null);
      setShadowError(null);
      return;
    }
    setCompileError(null);
    setShadowBusy(true);
    setShadowError(null);
    setShadowResult(null);
    try {
      const res = await fetch("/api/v1/rules/shadow-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          root_node: out.root,
          action: testAction,
        }),
      });
      const body = (await res.json().catch(() => ({}))) as RuleShadowTestResponse & {
        error?: string;
        detail?: unknown;
      };
      if (!res.ok) {
        const msg =
          typeof body.error === "string"
            ? body.error
            : `Shadow test failed (${res.status})`;
        setShadowError(msg);
        return;
      }
      setShadowResult(body as RuleShadowTestResponse);
    } catch {
      setShadowError("Network error while running shadow test.");
    } finally {
      setShadowBusy(false);
    }
  }, [blocks, testAction]);

  const rootHint = useMemo(() => {
    if (blocks.length >= 2) {
      return "Root shape: AndNode — { \"children\": [ … ] }";
    }
    return "Root shape: ConditionNode — { \"field\", \"operator\", \"value\" }";
  }, [blocks.length]);

  return (
    <div className="flex min-h-0 flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight text-slate-100">Visual Rule Builder</h1>
        <p className="max-w-3xl text-xs leading-relaxed text-slate-500">
          Stack condition blocks (Scratch-style). Each block picks a{" "}
          <span className="text-slate-400">TransactionSchema</span> field (plus the graph extension{" "}
          <span className="font-mono text-slate-400">graph_linked_to_blocked_count</span>), a Phase-3
          operator, and a value. Graph blocks count distinct <span className="text-slate-400">blocked</span>{" "}
          users sharing the same IP as the subject (Neo4j <span className="font-mono text-slate-500">ORDERED_FROM_IP</span>
          ). Example: <span className="font-mono text-slate-400">amount &gt; 100</span> AND{" "}
          <span className="font-mono text-slate-400">graph_linked_to_blocked_count &gt; 0</span> →{" "}
          <span className="text-slate-400">BLOCK</span>. Multiple blocks compile to an{" "}
          <span className="font-mono text-slate-400">AndNode</span> for the rule-engine sidecar. Use{" "}
          <span className="font-semibold text-slate-400">Test Rule</span> to replay the predicate
          against the last 1,000 historical audit rows (or a deterministic synthetic cohort when the
          audit DB is empty) before saving to <span className="font-mono text-slate-400">engine_rules</span>.
        </p>
        <p className="text-[11px] text-slate-600">{rootHint}</p>
      </div>

      <div className="flex flex-col gap-4">
        {blocks.map((block, index) => (
          <div key={block.id} className="relative flex flex-col gap-2">
            {index > 0 ? (
              <div
                className="mb-1 flex items-center gap-3 ps-1"
                aria-hidden
              >
                <div className="h-px flex-1 bg-gradient-to-r from-amber-600/40 via-amber-500/70 to-amber-600/40" />
                <span className="shrink-0 rounded-full border border-amber-700/60 bg-amber-950/80 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-amber-200">
                  And
                </span>
                <div className="h-px flex-1 bg-gradient-to-r from-amber-600/40 via-amber-500/70 to-amber-600/40" />
              </div>
            ) : null}

            <div
              className="relative overflow-hidden rounded-2xl border-2 border-slate-700/90 bg-gradient-to-b from-slate-900/95 to-slate-950 p-4 shadow-lg ring-1 ring-slate-800/80"
              style={{ boxShadow: "0 12px 40px -18px rgba(0,0,0,0.75)" }}
            >
              <div
                className="absolute -left-px top-8 h-10 w-3 rounded-r-md bg-slate-700/90"
                aria-hidden
              />
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  Block {index + 1}
                </span>
                <button
                  type="button"
                  onClick={() => removeBlock(block.id)}
                  disabled={!canRemove}
                  className="inline-flex size-8 items-center justify-center rounded-md border border-slate-700 text-slate-400 transition-colors hover:border-red-900/50 hover:bg-red-950/30 hover:text-red-200 disabled:pointer-events-none disabled:opacity-30"
                  aria-label="Remove block"
                >
                  <Trash2 className="size-3.5" strokeWidth={2} />
                </button>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="flex flex-col gap-1.5">
                  <label
                    className="text-[10px] font-semibold uppercase tracking-widest text-slate-500"
                    htmlFor={`${baseId}-f-${block.id}`}
                  >
                    Field
                  </label>
                  <select
                    id={`${baseId}-f-${block.id}`}
                    value={block.field}
                    onChange={(e) =>
                      updateBlock(block.id, {
                        field: e.target.value as ConditionBlock["field"],
                      })
                    }
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-slate-100 outline-none focus:border-amber-600/60"
                  >
                    {TRANSACTION_SCHEMA_FIELDS.map((f) => (
                      <option key={f} value={f}>
                        {TRANSACTION_FIELD_LABELS[f]}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col gap-1.5">
                  <label
                    className="text-[10px] font-semibold uppercase tracking-widest text-slate-500"
                    htmlFor={`${baseId}-o-${block.id}`}
                  >
                    Operator
                  </label>
                  <select
                    id={`${baseId}-o-${block.id}`}
                    value={block.operator}
                    onChange={(e) =>
                      updateBlock(block.id, {
                        operator: e.target.value as ConditionBlock["operator"],
                      })
                    }
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-slate-100 outline-none focus:border-amber-600/60"
                  >
                    {PHASE3_OPERATORS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col gap-1.5 sm:col-span-1">
                  <label
                    className="text-[10px] font-semibold uppercase tracking-widest text-slate-500"
                    htmlFor={`${baseId}-v-${block.id}`}
                  >
                    Value
                  </label>
                  <input
                    id={`${baseId}-v-${block.id}`}
                    value={block.valueRaw}
                    onChange={(e) => updateBlock(block.id, { valueRaw: e.target.value })}
                    placeholder="500, US, JSON…"
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-xs text-slate-100 outline-none placeholder:text-slate-600 focus:border-amber-600/60"
                  />
                </div>
              </div>
            </div>
          </div>
        ))}

        <button
          type="button"
          onClick={addBlock}
          className="inline-flex items-center justify-center gap-2 self-start rounded-lg border border-dashed border-slate-600 px-4 py-2.5 text-xs font-medium text-slate-300 transition-colors hover:border-amber-700/60 hover:bg-amber-950/20 hover:text-amber-100"
        >
          <Plus className="size-4" strokeWidth={2} />
          Add condition block
        </button>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handlePreview}
            className="inline-flex items-center gap-2 rounded-lg border border-amber-700/70 bg-amber-950/40 px-4 py-2.5 text-sm font-semibold text-amber-100 transition-colors hover:bg-amber-900/50"
          >
            <Braces className="size-4" strokeWidth={2} />
            Preview JSON
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <label
              htmlFor={`${baseId}-test-action`}
              className="text-[10px] font-semibold uppercase tracking-widest text-slate-500"
            >
              Test action
            </label>
            <select
              id={`${baseId}-test-action`}
              value={testAction}
              onChange={(e) => setTestAction(e.target.value)}
              disabled={shadowBusy}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-slate-100 outline-none focus:border-violet-600/60"
            >
              {RULE_TEST_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void handleShadowTest()}
              disabled={shadowBusy}
              className="inline-flex items-center gap-2 rounded-lg border border-violet-600/70 bg-violet-950/50 px-4 py-2.5 text-sm font-semibold text-violet-100 transition-colors hover:bg-violet-900/55 disabled:opacity-50"
            >
              <FlaskConical className="size-4" strokeWidth={2} />
              {shadowBusy ? "Testing…" : "Test Rule"}
            </button>
          </div>
          {compileError ? (
            <p className="w-full text-xs text-red-400" role="alert">
              {compileError}
            </p>
          ) : null}
          {shadowError ? (
            <p className="w-full text-xs text-red-400" role="alert">
              {shadowError}
            </p>
          ) : null}
        </div>

        {shadowResult ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <h2 className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
              Shadow test (last {shadowResult.sample_size} transactions)
            </h2>
            <p className="text-sm leading-relaxed text-slate-200">{shadowResult.summary_line}</p>
            <p className="mt-1 font-mono text-[11px] text-slate-500">
              Matched {shadowResult.matched_count} · rate {(shadowResult.match_rate * 100).toFixed(1)}%
            </p>
            {shadowResult.warning ? (
              <p
                className="mt-3 rounded-md border border-red-800/60 bg-red-950/35 px-3 py-2 text-sm font-semibold uppercase tracking-wide text-red-200"
                role="alert"
              >
                {shadowResult.warning}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {preview ? (
        <div className="flex min-h-0 flex-col gap-2">
          <h2 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
            Compiled root (LogicalNode)
          </h2>
          <pre className="max-h-[min(60vh,28rem)] overflow-auto rounded-xl border border-slate-800 bg-slate-950/80 p-4 text-[11px] leading-relaxed text-emerald-100/90">
            {preview}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
