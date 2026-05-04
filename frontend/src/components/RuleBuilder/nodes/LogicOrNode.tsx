import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { NODE_TYPES } from "../compileToAST";

type LogicOrRfNode = Node<Record<string, never>, typeof NODE_TYPES.logicOr>;

export function LogicOrNode({ selected }: NodeProps<LogicOrRfNode>) {
  return (
    <div
      className={`rounded-lg border px-3 py-3 min-w-[120px] text-center shadow-md ${
        selected ? "border-rose-500 ring-1 ring-rose-500/40" : "border-surface-600"
      } bg-rose-950/40 text-rose-100`}
    >
      <div className="text-xs font-semibold tracking-wide">OR</div>
      <div className="text-[10px] text-rose-300/80 mt-1">Each branch → separate rule (Rust sums if multiple hit)</div>
      <Handle type="target" position={Position.Left} id="o-in" className="!bg-rose-400 !w-2.5 !h-2.5" />
      <Handle type="source" position={Position.Right} id="o-out" className="!bg-rose-300 !w-2.5 !h-2.5" />
    </div>
  );
}
