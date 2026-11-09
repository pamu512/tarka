import { EVALUATOR_OPS, isWidgetOp, type ConditionRow } from "../model/uiPack";
import type { CatalogFieldDef } from "../registry/catalogToFields";

type Props = {
  ruleId: string;
  conditions: ConditionRow[];
  fields: CatalogFieldDef[];
  onChange: (conditionId: string, patch: Partial<ConditionRow>) => void;
  onAdd: () => void;
  onRemove: (conditionId: string) => void;
  onMove: (conditionId: string, dir: -1 | 1) => void;
};

function fieldDef(fields: CatalogFieldDef[], name: string): CatalogFieldDef | undefined {
  return fields.find((f) => f.name === name);
}

function ValueWidget({
  row,
  fields,
  onChange,
}: {
  row: ConditionRow;
  fields: CatalogFieldDef[];
  onChange: (patch: Partial<ConditionRow>) => void;
}) {
  const def = fieldDef(fields, row.field);
  const widget = isWidgetOp(row.op);

  if (!widget) {
    return (
      <input
        aria-label={`Value for ${row.field || "condition"} (JSON)`}
        className="flex-1 min-w-[80px] bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
        value={typeof row.value === "string" ? row.value : JSON.stringify(row.value ?? null)}
        onChange={(e) => {
          const raw = e.target.value;
          try {
            onChange({ value: JSON.parse(raw) as unknown });
          } catch {
            onChange({ value: raw });
          }
        }}
        placeholder="JSON value"
      />
    );
  }

  if (row.op === "is_true" || row.op === "is_false") {
    return <div className="flex-1" aria-hidden />;
  }

  if (row.op === "in") {
    const display = Array.isArray(row.value)
      ? (row.value as unknown[]).join(", ")
      : String(row.value ?? "");
    return (
      <input
        aria-label={`List value for ${row.field || "condition"}`}
        className="flex-1 min-w-[80px] bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
        value={display}
        onChange={(e) => {
          const parts = e.target.value
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
          onChange({ value: parts });
        }}
        placeholder="val1, val2"
      />
    );
  }

  const numeric =
    def?.valueType === "number" ||
    row.op === "gt" ||
    row.op === "gte" ||
    row.op === "lt" ||
    row.op === "lte";

  if (numeric) {
    return (
      <input
        type="number"
        aria-label={`Numeric value for ${row.field || "condition"}`}
        className="flex-1 min-w-[80px] bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
        value={row.value === undefined || row.value === null ? "" : String(row.value)}
        onChange={(e) => {
          const n = Number(e.target.value);
          onChange({ value: Number.isFinite(n) ? n : e.target.value });
        }}
      />
    );
  }

  if (def?.valueType === "bool") {
    return (
      <select
        aria-label={`Boolean value for ${row.field || "condition"}`}
        className="flex-1 bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
        value={String(row.value ?? "true")}
        onChange={(e) => onChange({ value: e.target.value === "true" })}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  return (
    <input
      aria-label={`Text value for ${row.field || "condition"}`}
      className="flex-1 min-w-[80px] bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
      value={String(row.value ?? "")}
      onChange={(e) => onChange({ value: e.target.value })}
    />
  );
}

export function ConditionGroupEditor({
  ruleId,
  conditions,
  fields,
  onChange,
  onAdd,
  onRemove,
  onMove,
}: Props) {
  const fieldNames = fields.map((f) => f.name);
  const listId = `studio-fields-${ruleId}`;

  return (
    <div className="space-y-2" role="group" aria-label="Conditions">
      <datalist id={listId}>
        {fieldNames.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      {conditions.map((row, i) => {
        const widget = isWidgetOp(row.op);
        return (
          <div key={row.id} className="flex flex-wrap items-center gap-2 group">
            <span className="w-8 text-[10px] text-gray-600 text-right shrink-0 font-medium">
              {i === 0 ? "IF" : "AND"}
            </span>
            <label className="sr-only" htmlFor={`${row.id}-field`}>
              Field
            </label>
            <input
              id={`${row.id}-field`}
              list={listId}
              value={row.field}
              onChange={(e) => onChange(row.id, { field: e.target.value })}
              className="w-44 bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
              placeholder="field"
            />
            <label className="sr-only" htmlFor={`${row.id}-op`}>
              Operator
            </label>
            <select
              id={`${row.id}-op`}
              value={EVALUATOR_OPS.includes(row.op) ? row.op : "__custom__"}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "__custom__") return;
                onChange(row.id, { op: v });
              }}
              className="w-40 bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
            >
              {EVALUATOR_OPS.map((op) => (
                <option key={op} value={op}>
                  {op}
                </option>
              ))}
              {!EVALUATOR_OPS.includes(row.op) && (
                <option value="__custom__">{row.op}</option>
              )}
            </select>
            {!EVALUATOR_OPS.includes(row.op) && (
              <input
                aria-label="Custom operator"
                className="w-28 bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
                value={row.op}
                onChange={(e) => onChange(row.id, { op: e.target.value })}
              />
            )}
            <ValueWidget
              row={row}
              fields={fields}
              onChange={(patch) => onChange(row.id, patch)}
            />
            <button
              type="button"
              aria-label={`Move condition ${i + 1} up`}
              disabled={i === 0}
              onClick={() => onMove(row.id, -1)}
              className="text-gray-500 hover:text-gray-300 disabled:opacity-30 px-1 focus:outline-none focus:ring-1 focus:ring-brand-500 rounded"
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`Move condition ${i + 1} down`}
              disabled={i === conditions.length - 1}
              onClick={() => onMove(row.id, 1)}
              className="text-gray-500 hover:text-gray-300 disabled:opacity-30 px-1 focus:outline-none focus:ring-1 focus:ring-brand-500 rounded"
            >
              ↓
            </button>
            <button
              type="button"
              aria-label={`Remove condition ${i + 1}`}
              onClick={() => onRemove(row.id)}
              className="text-gray-500 hover:text-red-400 px-1 focus:outline-none focus:ring-1 focus:ring-brand-500 rounded"
            >
              ×
            </button>
          </div>
        );
      })}
      <button
        type="button"
        onClick={onAdd}
        className="text-xs text-brand-400 hover:text-brand-300 focus:outline-none focus:ring-1 focus:ring-brand-500 rounded px-1"
      >
        + Add condition
      </button>
    </div>
  );
}
