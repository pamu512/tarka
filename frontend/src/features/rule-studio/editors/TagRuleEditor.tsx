type Props = {
  ruleId: string;
  tags: string[];
  onChange: (tags: string[]) => void;
};

export function TagRuleEditor({ ruleId, tags, onChange }: Props) {
  const id = `tags-${ruleId}`;
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-xs text-gray-400 shrink-0">
        Tags
      </label>
      <input
        id={id}
        aria-label="Rule tags (comma-separated)"
        value={tags.join(", ")}
        onChange={(e) => {
          const next = e.target.value
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
          onChange(next);
        }}
        placeholder="tag1, tag2"
        className="flex-1 bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
    </div>
  );
}
