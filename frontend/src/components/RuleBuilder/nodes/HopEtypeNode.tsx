import { Handle, Position, useReactFlow, type Node, type NodeProps } from "@xyflow/react";

import { CATALOG_HOPS } from "../../../domain/authorCatalog";
import { NODE_TYPES } from "../compileToAST";

export type HopEtypeNodeData = { etype: string };

type HopEtypeRfNode = Node<HopEtypeNodeData, typeof NODE_TYPES.hopEtype>;

export function HopEtypeNode({ id, data, selected }: NodeProps<HopEtypeRfNode>) {
  const { setNodes } = useReactFlow();

  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[200px] shadow-md ${
        selected ? "border-cyan-500 ring-1 ring-cyan-500/40" : "border-surface-600"
      } bg-surface-900 text-slate-100`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Hop etype</div>
      <label className="block text-[10px] text-slate-500 mb-0.5">Etype</label>
      <select
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs font-mono"
        value={data.etype}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, etype: e.target.value } } : n)))
        }
      >
        {CATALOG_HOPS.map((etype) => (
          <option key={etype} value={etype}>
            {etype}
          </option>
        ))}
      </select>
      <Handle type="source" position={Position.Right} id="he-out" className="!bg-cyan-400 !w-2.5 !h-2.5" />
    </div>
  );
}
