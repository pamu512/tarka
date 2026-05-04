import { Handle, Position, useEdges, useNodes, useReactFlow, type Node, type NodeProps } from "@xyflow/react";

import { allowedOpsForKind, NODE_TYPES, type FeatureNodeData, type OperatorNodeData } from "../compileToAST";

type OperatorRfNode = Node<OperatorNodeData, typeof NODE_TYPES.operator>;

export function OperatorNode({ id, data, selected }: NodeProps<OperatorRfNode>) {
  const { setNodes } = useReactFlow();
  const edges = useEdges();
  const nodes = useNodes();
  const src = edges.find((e) => e.target === id && e.targetHandle === "f-in")?.source;
  const feat = src ? nodes.find((n) => n.id === src) : undefined;
  const kind = feat?.type === NODE_TYPES.feature ? (feat.data as FeatureNodeData).featureKind : "string";
  const ops = allowedOpsForKind(kind);

  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[220px] shadow-md ${
        selected ? "border-amber-500 ring-1 ring-amber-500/40" : "border-surface-600"
      } bg-surface-900 text-slate-100`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Operator</div>
      <Handle type="target" position={Position.Left} id="f-in" className="!bg-emerald-500 !w-2.5 !h-2.5" />
      <select
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs mb-2"
        value={ops.includes(data.op as (typeof ops)[number]) ? data.op : ops[0]}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, op: e.target.value } } : n)))
        }
      >
        {ops.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      <textarea
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs font-mono min-h-[52px]"
        placeholder='Value (JSON array for in/not_in, e.g. ["US","CA"])'
        value={data.valueStr}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, valueStr: e.target.value } } : n)))
        }
      />
      <p className="text-[10px] text-slate-500 mt-1">Upstream feature type: {kind}</p>
      <Handle type="source" position={Position.Right} id="o-out" className="!bg-amber-400 !w-2.5 !h-2.5" />
    </div>
  );
}
