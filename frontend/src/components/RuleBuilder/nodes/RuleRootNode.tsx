import { Handle, Position, useReactFlow, type Node, type NodeProps } from "@xyflow/react";

import { NODE_TYPES, type RuleRootNodeData } from "../compileToAST";

type RuleRootRfNode = Node<RuleRootNodeData, typeof NODE_TYPES.ruleRoot>;

export function RuleRootNode({ id, data, selected }: NodeProps<RuleRootRfNode>) {
  const { setNodes } = useReactFlow();

  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[240px] shadow-md ${
        selected ? "border-sky-400 ring-1 ring-sky-400/40" : "border-surface-600"
      } bg-slate-900 text-slate-100`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Rule output</div>
      <Handle type="target" position={Position.Left} id="r-in" className="!bg-sky-400 !w-2.5 !h-2.5" />
      <label className="text-[10px] text-slate-500">Rule id</label>
      <input
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs mb-2"
        value={data.ruleId}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, ruleId: e.target.value } } : n)))
        }
      />
      <label className="text-[10px] text-slate-500">Tags (comma)</label>
      <input
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs mb-2"
        value={data.tagsStr}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, tagsStr: e.target.value } } : n)))
        }
      />
      <label className="text-[10px] text-slate-500">Score delta</label>
      <input
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs mb-2"
        value={data.scoreDeltaStr}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, scoreDeltaStr: e.target.value } } : n)))
        }
      />
      <label className="text-[10px] text-slate-500">Description</label>
      <input
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs"
        value={data.description}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, description: e.target.value } } : n)))
        }
      />
    </div>
  );
}
