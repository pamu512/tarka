import { createContext, useContext } from "react";
import { Handle, Position, useReactFlow, type Node, type NodeProps } from "@xyflow/react";

import { featurePickerGroups, type AuthorCatalog } from "../../../domain/authorCatalog";
import { fallbackAuthorCatalog } from "../../../domain/authorCatalogFallback";
import type { FeatureNodeData } from "../compileToAST";
import { NODE_TYPES } from "../compileToAST";

export const FeatureCatalogContext = createContext<AuthorCatalog>(fallbackAuthorCatalog());

type FeatureRfNode = Node<FeatureNodeData, typeof NODE_TYPES.feature>;

export function FeatureNode({ id, data, selected }: NodeProps<FeatureRfNode>) {
  const { setNodes } = useReactFlow();
  const catalog = useContext(FeatureCatalogContext);
  const groups = featurePickerGroups(catalog);
  const catalogNames = new Set(groups.flatMap((g) => g.options.map((o) => o.name)));

  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[200px] shadow-md ${
        selected ? "border-sky-500 ring-1 ring-sky-500/40" : "border-surface-600"
      } bg-surface-900 text-slate-100`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Feature</div>
      <select
        className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs mb-2 font-mono"
        value={data.field}
        onChange={(e) =>
          setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...data, field: e.target.value } } : n)))
        }
      >
        {groups.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.options.map((o) => (
              <option key={o.name} value={o.name}>
                {o.window ? `${o.window} ${o.name}` : o.name}
              </option>
            ))}
          </optgroup>
        ))}
        {data.field && !catalogNames.has(data.field) ? <option value={data.field}>{data.field}</option> : null}
      </select>
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
