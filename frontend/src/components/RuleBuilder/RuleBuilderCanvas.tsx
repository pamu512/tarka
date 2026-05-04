import { useCallback, useState } from "react";
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

  const onConnect = useCallback(
    (params: Connection) => {
      const ok = isValidRuleConnection(params, getNodes());
      if (!ok) {
        setCompileErr("Invalid connection: connect Feature → Operator → (AND/OR) → Rule root only.");
        return;
      }
      setCompileErr("");
      setEdges((eds) => addEdge({ ...params, animated: true }, eds));
    },
    [getNodes, setEdges],
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

  return (
    <div className="space-y-3">
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
      {compiledDeploy ? (
        <div>
          <div className="text-xs text-slate-500 mb-1">Compiled JSON (Rust `when` shape — client mirror of decision-api)</div>
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
