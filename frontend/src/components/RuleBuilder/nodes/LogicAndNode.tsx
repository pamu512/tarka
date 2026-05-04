import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { NODE_TYPES } from "../compileToAST";

type LogicAndRfNode = Node<Record<string, never>, typeof NODE_TYPES.logicAnd>;

export function LogicAndNode({ selected }: NodeProps<LogicAndRfNode>) {
  return (
    <div
      className={`rounded-lg border px-3 py-3 min-w-[120px] text-center shadow-md ${
        selected ? "border-violet-500 ring-1 ring-violet-500/40" : "border-surface-600"
      } bg-violet-950/40 text-violet-100`}
    >
      <div className="text-xs font-semibold tracking-wide">AND</div>
      <div className="text-[10px] text-violet-300/80 mt-1">All inputs must match</div>
      <Handle type="target" position={Position.Left} id="a-in" className="!bg-violet-400 !w-2.5 !h-2.5" />
      <Handle type="source" position={Position.Right} id="a-out" className="!bg-violet-300 !w-2.5 !h-2.5" />
    </div>
  );
}
