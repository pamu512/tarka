import { useCallback, useMemo, useState } from "react";
import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { rules } from "../../api/client";
import type { VisualAstPack } from "../../types/rules";
import {
  compileToAST,
  compileVisualToDeployedJsonPack,
  isValidRuleConnection,
  NODE_TYPES,
  type FeatureNodeData,
  type OperatorNodeData,
  type RuleRootNodeData,
} from "./compileToAST";
import { connectionCreatesDirectedCycle } from "./graphCycle";
import { defaultPackNameFromCanvas, readRuleRootMeta } from "./compileFlowToJsonAst";
import { tryCompileFlowToJsonAst, validateCanvasForAstSave } from "./validateRuleBuilderCanvas";
import { FeatureNode } from "./nodes/FeatureNode";
import { LogicAndNode } from "./nodes/LogicAndNode";
import { LogicOrNode } from "./nodes/LogicOrNode";
import { OperatorNode } from "./nodes/OperatorNode";
import { RuleRootNode } from "./nodes/RuleRootNode";
import { TestRuleModal } from "./TestRuleModal";

const initialNodes: Node[] = [
  {
    id: "feat-1",
    type: NODE_TYPES.feature,
    position: { x: 0, y: 40 },
    data: { field: "transaction_amount", featureKind: "number" } satisfies FeatureNodeData,
  },
  {
    id: "op-1",
    type: NODE_TYPES.operator,
    position: { x: 260, y: 32 },
    data: { op: "gte", valueStr: "5000" } satisfies OperatorNodeData,
  },
  {
    id: "and-1",
    type: NODE_TYPES.logicAnd,
    position: { x: 520, y: 48 },
    data: {},
  },
  {
    id: "root-1",
    type: NODE_TYPES.ruleRoot,
    position: { x: 720, y: 24 },
    data: {
      ruleId: "high_value_payment",
      tagsStr: "queue:risk_ops_review",
      scoreDeltaStr: "15",
      description: "High-value threshold",
    } satisfies RuleRootNodeData,
  },
];

const initialEdges: Edge[] = [
  { id: "e1", source: "feat-1", target: "op-1", sourceHandle: "f-out", targetHandle: "f-in" },
  { id: "e2", source: "op-1", target: "and-1", sourceHandle: "o-out", targetHandle: "a-in" },
  { id: "e3", source: "and-1", target: "root-1", sourceHandle: "a-out", targetHandle: "r-in" },
];

const nodeTypes = {
  [NODE_TYPES.feature]: FeatureNode,
  [NODE_TYPES.operator]: OperatorNode,
  [NODE_TYPES.logicAnd]: LogicAndNode,
  [NODE_TYPES.logicOr]: LogicOrNode,
  [NODE_TYPES.ruleRoot]: RuleRootNode,
} satisfies NodeTypes;

function CanvasInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const { getNodes } = useReactFlow();
  const [compiledPack, setCompiledPack] = useState<VisualAstPack | null>(null);
  const [compiledDeploy, setCompiledDeploy] = useState<string>("");
  const [compileErr, setCompileErr] = useState<string>("");
  const [serverCompile, setServerCompile] = useState<string>("");
  const [serverErr, setServerErr] = useState<string>("");
  const [testOpen, setTestOpen] = useState(false);
  const [packName, setPackName] = useState("");
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const [saveOk, setSaveOk] = useState("");

  const saveReadiness = useMemo(() => validateCanvasForAstSave(nodes, edges), [nodes, edges]);
  const astLive = useMemo(() => tryCompileFlowToJsonAst(nodes, edges), [nodes, edges]);

  const onConnect = useCallback(
    (params: Connection) => {
      const ok = isValidRuleConnection(params, getNodes());
      if (!ok) {
        setCompileErr("Invalid connection: connect Feature → Operator → (AND/OR) → Rule root only.");
        return;
      }
      if (connectionCreatesDirectedCycle(nodes, edges, params)) {
        setCompileErr("That connection would create a directed cycle in the graph.");
        return;
      }
      setCompileErr("");
      setEdges((eds) => addEdge({ ...params, animated: true }, eds));
    },
    [edges, getNodes, nodes, setEdges],
  );

  const handleCompileLocal = useCallback(() => {
    setCompileErr("");
    setServerErr("");
    try {
      const pack = compileToAST(getNodes(), edges);
      setCompiledPack(pack);
      setCompiledDeploy(JSON.stringify(compileVisualToDeployedJsonPack(pack), null, 2));
    } catch (e) {
      setCompiledPack(null);
      setCompiledDeploy("");
      setCompileErr(e instanceof Error ? e.message : String(e));
    }
  }, [edges, getNodes]);

  const handleSaveAstPack = useCallback(async () => {
    setSaveErr("");
    setSaveOk("");
    const v = validateCanvasForAstSave(nodes, edges);
    if (!v.ok) {
      setSaveErr(v.errors.join("\n"));
      return;
    }
    const built = tryCompileFlowToJsonAst(nodes, edges);
    if (!built.ok) {
      setSaveErr(built.errors.join("\n"));
      return;
    }
    let meta: ReturnType<typeof readRuleRootMeta>;
    try {
      meta = readRuleRootMeta(nodes);
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e));
      return;
    }
    const name = packName.trim() || defaultPackNameFromCanvas(nodes);
    setSaveBusy(true);
    try {
      const out = (await rules.create({
        name,
        rules: [
          {
            id: meta.ruleId,
            when: [],
            tags: meta.tags,
            score_delta: meta.scoreDelta,
            description: meta.description,
            when_ast: built.ast,
          },
        ],
        tag_rules: [],
      })) as { file?: string };
      setSaveOk(`Pack created: ${out.file ?? "ok"}. Rules reload on the server.`);
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaveBusy(false);
    }
  }, [edges, nodes, packName]);

  const handleCompileServer = useCallback(async () => {
    setServerErr("");
    setServerCompile("");
    let pack: VisualAstPack;
    try {
      pack = compileToAST(getNodes(), edges);
    } catch (e) {
      setCompileErr(e instanceof Error ? e.message : String(e));
      return;
    }
    const base = (import.meta.env.VITE_DECISION_API_URL as string | undefined)?.replace(/\/$/, "") || "/api/decisions";
    const key = (import.meta.env.VITE_API_KEY as string | undefined) || "";
    try {
      const r = await fetch(`${base}/v1/rules/visual/compile`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(key ? { "X-Api-Key": key } : {}) },
        body: JSON.stringify(pack),
      });
      const j = await r.json();
      if (!r.ok) {
        setServerErr(JSON.stringify(j, null, 2));
        return;
      }
      setServerCompile(JSON.stringify(j, null, 2));
    } catch (e) {
      setServerErr(e instanceof Error ? e.message : String(e));
    }
  }, [edges, getNodes]);

  const addNode = useCallback(
    (type: string, data: Record<string, unknown>) => {
      const id = `${type}-${Date.now()}`;
      setNodes((ns) => [...ns, { id, type, position: { x: 40 + ns.length * 12, y: 280 + ns.length * 8 }, data } as Node]);
    },
    [setNodes],
  );

  const canSaveAst = saveReadiness.ok && !saveBusy;

  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-end gap-2 max-w-xl">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Pack name (POST /v1/rules)
          <input
            type="text"
            value={packName}
            onChange={(e) => setPackName(e.target.value)}
            placeholder={defaultPackNameFromCanvas(nodes)}
            className="rounded border border-surface-600 bg-surface-900 px-2 py-1.5 text-sm text-gray-200"
          />
        </label>
        <button
          type="button"
          disabled={!canSaveAst}
          title={!saveReadiness.ok ? saveReadiness.errors.join(" | ") : undefined}
          className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium shrink-0"
          onClick={() => void handleSaveAstPack()}
        >
          {saveBusy ? "Saving…" : "Save AST pack"}
        </button>
      </div>
      {!saveReadiness.ok ? (
        <p className="text-xs text-amber-500/90 whitespace-pre-wrap">{saveReadiness.errors.join("\n")}</p>
      ) : null}
      {saveErr ? (
        <pre className="text-xs bg-red-950/50 border border-red-900/60 rounded p-2 text-red-200 overflow-auto whitespace-pre-wrap">{saveErr}</pre>
      ) : null}
      {saveOk ? <p className="text-xs text-emerald-400">{saveOk}</p> : null}
      <div className="flex flex-wrap gap-2 items-center text-xs">
        <span className="text-slate-500 mr-2">Add:</span>
        <button type="button" className="px-2 py-1 rounded bg-surface-800 border border-surface-600" onClick={() => addNode(NODE_TYPES.feature, { field: "new_field", featureKind: "number" })}>
          Feature
        </button>
        <button type="button" className="px-2 py-1 rounded bg-surface-800 border border-surface-600" onClick={() => addNode(NODE_TYPES.operator, { op: "eq", valueStr: "" })}>
          Operator
        </button>
        <button type="button" className="px-2 py-1 rounded bg-surface-800 border border-surface-600" onClick={() => addNode(NODE_TYPES.logicAnd, {})}>
          AND
        </button>
        <button type="button" className="px-2 py-1 rounded bg-surface-800 border border-surface-600" onClick={() => addNode(NODE_TYPES.logicOr, {})}>
          OR
        </button>
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          className="px-3 py-2 rounded bg-sky-600 text-white text-sm"
          onClick={() => void handleCompileServer()}
        >
          Validate on server (POST /v1/rules/visual/compile)
        </button>
        <button type="button" className="px-3 py-2 rounded bg-emerald-700 text-white text-sm" onClick={handleCompileLocal}>
          Compile to AST (client)
        </button>
        <button
          type="button"
          className="px-3 py-2 rounded bg-violet-700 text-white text-sm disabled:opacity-40"
          disabled={!compiledPack}
          onClick={() => setTestOpen(true)}
        >
          Test rule…
        </button>
        <span className="text-xs text-slate-500">Drag from handles; invalid wiring is rejected.</span>
      </div>
      {compileErr ? <p className="text-sm text-amber-500">{compileErr}</p> : null}
      {serverErr ? (
        <pre className="text-xs bg-red-950/40 border border-red-900/50 rounded p-2 text-red-200 overflow-auto">{serverErr}</pre>
      ) : null}
      <div className="h-[min(560px,70vh)] w-full rounded-lg border border-surface-700 bg-surface-950">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
          <Controls />
        </ReactFlow>
      </div>
      <div>
        <div className="text-xs text-slate-500 mb-1">
          JSON AST (client) — must match <code className="text-slate-400">decision_api.ast_models.JsonAstNode</code>
        </div>
        {astLive.ok ? (
          <pre className="text-xs bg-black/40 border border-surface-700 rounded p-3 overflow-auto text-cyan-200 max-h-48">
            {JSON.stringify(astLive.ast, null, 2)}
          </pre>
        ) : (
          <p className="text-xs text-amber-600/90 whitespace-pre-wrap">{astLive.errors.join("\n")}</p>
        )}
      </div>
      {compiledDeploy ? (
        <div>
          <div className="text-xs text-slate-500 mb-1">Legacy flat `when` JSON (dry-run / GitOps compile path)</div>
          <pre className="text-xs bg-black/40 border border-surface-700 rounded p-3 overflow-auto text-emerald-200 max-h-64">
            {compiledDeploy}
          </pre>
        </div>
      ) : null}
      {serverCompile ? (
        <div>
          <div className="text-xs text-slate-500 mb-1">Server compile response</div>
          <pre className="text-xs bg-black/40 border border-surface-700 rounded p-3 overflow-auto text-sky-200 max-h-64">
            {serverCompile}
          </pre>
        </div>
      ) : null}
      <TestRuleModal open={testOpen} onClose={() => setTestOpen(false)} visualPack={compiledPack} />
    </div>
  );
}

export function RuleBuilderCanvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}
