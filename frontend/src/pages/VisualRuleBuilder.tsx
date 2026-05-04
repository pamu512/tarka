import { useState } from "react";
import { PageTitle } from "../components/PageTitle";

/**
 * Visual rule builder (AST editor). Compiles via decision-api POST /v1/rules/visual/compile.
 */
export default function VisualRuleBuilder() {
  const [name, setName] = useState("tenant_acme_pack");
  const [field, setField] = useState("payload.amount");
  const [op, setOp] = useState("gte");
  const [value, setValue] = useState("5000");
  const [out, setOut] = useState<string>("");

  const compile = async () => {
    const base = (import.meta.env.VITE_DECISION_API_URL as string | undefined)?.replace(/\/$/, "") || "";
    const ast = {
      name,
      rules: [
        {
          id: "crypto_high_value",
          all_of: [{ field, op, value: Number(value) || value }],
          tags: ["queue:crypto_escalation"],
          score_delta: 15,
          description: "High-value crypto heuristic",
        },
      ],
      tag_rules: [],
    };
    const r = await fetch(`${base}/v1/rules/visual/compile`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Api-Key": (import.meta.env.VITE_API_KEY as string) || "" },
      body: JSON.stringify(ast),
    });
    const j = await r.json();
    setOut(JSON.stringify(j, null, 2));
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <PageTitle module="rules">
        Visual rule builder
        <span className="block text-xs font-normal text-gray-500 mt-1">
          Compile to JSON rule pack + Rego stub (GitOps approval required)
        </span>
      </PageTitle>
      <div className="grid gap-2 text-sm">
        <label className="text-gray-400">Pack name</label>
        <input className="bg-surface-800 border border-surface-600 rounded px-2 py-1" value={name} onChange={(e) => setName(e.target.value)} />
        <label className="text-gray-400">Condition field</label>
        <input className="bg-surface-800 border border-surface-600 rounded px-2 py-1" value={field} onChange={(e) => setField(e.target.value)} />
        <label className="text-gray-400">Operator</label>
        <select className="bg-surface-800 border border-surface-600 rounded px-2 py-1" value={op} onChange={(e) => setOp(e.target.value)}>
          {["eq", "ne", "gt", "gte", "lt", "lte", "contains"].map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        <label className="text-gray-400">Value</label>
        <input className="bg-surface-800 border border-surface-600 rounded px-2 py-1" value={value} onChange={(e) => setValue(e.target.value)} />
        <button type="button" className="mt-2 px-3 py-2 rounded bg-sky-600 text-white text-sm" onClick={() => void compile()}>
          Compile
        </button>
      </div>
      {out && (
        <pre className="text-xs bg-black/40 border border-surface-700 rounded p-3 overflow-auto text-emerald-200">{out}</pre>
      )}
    </div>
  );
}
