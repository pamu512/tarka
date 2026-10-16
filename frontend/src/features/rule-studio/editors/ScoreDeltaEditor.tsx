type Props = {
  ruleId: string;
  value: number;
  onChange: (score_delta: number) => void;
};

export function ScoreDeltaEditor({ ruleId, value, onChange }: Props) {
  const id = `score-delta-${ruleId}`;
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-xs text-gray-400 shrink-0">
        Score delta
      </label>
      <input
        id={id}
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-24 bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
    </div>
  );
}
