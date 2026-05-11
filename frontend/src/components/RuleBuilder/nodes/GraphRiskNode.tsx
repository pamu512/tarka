import { Handle, Position, useReactFlow, type Node, type NodeProps } from "@xyflow/react";

import { NODE_TYPES, type GraphRiskNodeData } from "../compileToAST";

type GraphRiskRfNode = Node<GraphRiskNodeData, typeof NODE_TYPES.graphRisk>;

export function GraphRiskNode({ id, data, selected }: NodeProps<GraphRiskRfNode>) {
  const { setNodes } = useReactFlow();

  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[200px] shadow-md ${
        selected ? "border-cyan-500 ring-1 ring-cyan-500/40" : "border-surface-600"
      } bg-surface-900 text-slate-100`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Graph risk</div>
      <p className="text-[10px] text-slate-400 mb-2">
        Fires when <code className="text-cyan-300/90">context.graph_score</code> &gt; threshold (Rust GraphMatch).
      </p>
      <label className="block text-[10px] text-slate-500 mb-0.5">Threshold (0–1 typical)</label>
      <input
        type="text"
        inputMode="decimal"
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs font-mono"
        value={data.thresholdStr}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, thresholdStr: e.target.value } } : n)))
        }
        placeholder="0.8"
      />
      <Handle type="source" position={Position.Right} id="gr-out" className="!bg-cyan-400 !w-2.5 !h-2.5" />
    </div>
  );
}
