import { Handle, Position, useReactFlow, type Node, type NodeProps } from "@xyflow/react";

import type { FeatureNodeData } from "../compileToAST";
import { NODE_TYPES } from "../compileToAST";

type FeatureRfNode = Node<FeatureNodeData, typeof NODE_TYPES.feature>;

export function FeatureNode({ id, data, selected }: NodeProps<FeatureRfNode>) {
  const { setNodes } = useReactFlow();

  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[200px] shadow-md ${
        selected ? "border-sky-500 ring-1 ring-sky-500/40" : "border-surface-600"
      } bg-surface-900 text-slate-100`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Feature</div>
      <input
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs mb-2"
        placeholder="e.g. transaction_amount"
        value={data.field}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, field: e.target.value } } : n)))
        }
      />
      <select
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs"
        value={data.featureKind}
        onChange={(e) =>
          setNodes((ns) =>
            ns.map((n) =>
              n.id === id ? { ...n, data: { ...data, featureKind: e.target.value as FeatureNodeData["featureKind"] } } : n,
            ),
          )
        }
      >
        <option value="number">Number</option>
        <option value="string">String</option>
        <option value="boolean">Boolean</option>
      </select>
      <Handle type="source" position={Position.Right} id="f-out" className="!bg-emerald-500 !w-2.5 !h-2.5" />
    </div>
  );
}
