import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { PageTitle } from "../components/PageTitle";
import { RuleBuilderCanvas } from "../components/RuleBuilder";
import { seedCanvasFromLeftover } from "../components/RuleBuilder/seedCanvasFromLeftover";
import type { AuthorCatalog } from "../domain/authorCatalog";
import { loadAuthorCatalog } from "../domain/authorCatalogSession";
import { NODE_TYPES, type RuleRootNodeData } from "../components/RuleBuilder/compileToAST";

function huntBackHref(q: URLSearchParams): string {
  const back = new URLSearchParams();
  for (const key of ["entity_id", "tenant_id", "decision_id", "leftover_id", "pack", "hits"]) {
    const v = q.get(key);
    if (v) back.set(key, v);
  }
  return `/graph?${back}`;
}

function emptyLeftoverGraph() {
  return {
    nodes: [
      {
        id: "root-1",
        type: NODE_TYPES.ruleRoot,
        position: { x: 720, y: 24 },
        data: {
          ruleId: "observe_draft",
          tagsStr: "",
          scoreDeltaStr: "0",
          description: "",
        } satisfies RuleRootNodeData,
      },
    ],
    edges: [],
  };
}

/**
 * Visual rule builder — drag-and-drop React Flow canvas whose save path emits a
 * `JsonAstNode` tree aligned with `decision_api.ast_models` (AND/OR + typed condition leaves).
 */
export default function VisualRuleBuilder() {
  const [searchParams] = useSearchParams();
  const [catalog, setCatalog] = useState<AuthorCatalog | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadAuthorCatalog().then((row) => {
      if (!cancelled) setCatalog(row);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const leftover = searchParams.get("from") === "leftover";
  const seeded = useMemo(
    () => (catalog && leftover ? seedCanvasFromLeftover(catalog, searchParams) : null),
    [catalog, leftover, searchParams],
  );

  const leftoverId = searchParams.get("leftover_id")?.trim() || "missing";
  const pack = searchParams.get("pack")?.trim() || "missing";
  const hits = searchParams.get("hits")?.trim() || "—";

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <PageTitle module="rules">
        Visual rule builder
        <span className="block text-xs font-normal text-gray-500 mt-1">
          Drag from handles to wire <strong>Feature</strong> → <strong>Operator</strong> → <strong>AND / OR</strong> →{" "}
          <strong>Rule root</strong>. Cycles and empty logic nodes block <strong>Save AST pack</strong> (
          <code className="text-gray-400">POST /v1/rules</code> with <code className="text-gray-400">when_ast</code>). The
          live JSON panel mirrors the Python Pydantic schema. Use <strong>Validate on server</strong> for the legacy flat{" "}
          <code className="text-gray-400">when</code> compile path (<code className="text-gray-400">/v1/rules/visual/compile</code>) and{" "}
          <strong>Test rule…</strong> for dry-run.
        </span>
      </PageTitle>
      {leftover ? (
        <div
          data-testid="leftover-visual-banner"
          className="rounded-md border border-surface-700 bg-surface-900/70 px-3 py-2 text-sm text-slate-300 space-y-1"
        >
          <p>
            leftover {leftoverId} · pack {pack} · hits {hits}
          </p>
          {catalog && seeded === null ? (
            <p>No shipped hop or catalog key on this leftover — pick from the palette.</p>
          ) : null}
          <Link to={huntBackHref(searchParams)} className="text-brand-300 hover:underline text-xs">
            Back to Hunt
          </Link>
        </div>
      ) : null}
      {catalog ? (
        <RuleBuilderCanvas
          initialGraph={leftover ? (seeded ?? emptyLeftoverGraph()) : null}
          resetKey={leftover ? searchParams.toString() : "default"}
          catalog={catalog}
          fromLeftover={leftover}
        />
      ) : (
        <p className="text-sm text-slate-500">Loading catalog…</p>
      )}
    </div>
  );
}
