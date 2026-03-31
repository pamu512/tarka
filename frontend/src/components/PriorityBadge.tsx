interface PriorityBadgeProps {
  priority: string;
  className?: string;
}

const STYLES: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400 ring-red-500/30",
  high: "bg-orange-500/20 text-orange-400 ring-orange-500/30",
  medium: "bg-yellow-500/20 text-yellow-400 ring-yellow-500/30",
  low: "bg-green-500/20 text-green-400 ring-green-500/30",
};

export default function PriorityBadge({ priority, className = "" }: PriorityBadgeProps) {
  const style = STYLES[priority] ?? STYLES.low;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ring-1 ring-inset capitalize ${style} ${className}`}
    >
      {priority}
    </span>
  );
}
