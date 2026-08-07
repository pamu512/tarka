import { useEffect, useState } from "react";
import { decisions } from "../api/v1/decisions";

type ShadowPromoteGate = {
  schema_id: string;
  vertical?: string;
  blocked?: { promote_allowed?: boolean; blockers?: string[] };
  allowed?: { promote_allowed?: boolean };
  recipe_path?: string;
  smoke?: string;
};

export default function OpsShadow() {
  const [data, setData] = useState<ShadowPromoteGate | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    void decisions
      .shadowPromoteGate()
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-gray-100">Shadow vs primary</h1>
      <p className="text-sm text-gray-400">
        Promote-gate posture for shadow experiments. Warehouse diffs use the SQL recipe.
      </p>
      {err ? <p className="text-red-400">{err}</p> : null}
      {data ? (
        <>
          <div>
            Underpowered metrics: promote{" "}
            {data.blocked?.promote_allowed ? "allowed" : "blocked"}
          </div>
          <div>
            Healthy metrics: promote {data.allowed?.promote_allowed ? "allowed" : "blocked"}
          </div>
          <code className="text-xs">{data.recipe_path}</code>
        </>
      ) : null}
    </div>
  );
}
