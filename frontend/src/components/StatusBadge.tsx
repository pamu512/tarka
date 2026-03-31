interface StatusBadgeProps {
  status: string;
  className?: string;
}

const STYLES: Record<string, string> = {
  open: "bg-blue-500/20 text-blue-400 ring-blue-500/30",
  investigating: "bg-amber-500/20 text-amber-400 ring-amber-500/30",
  resolved: "bg-green-500/20 text-green-400 ring-green-500/30",
  closed: "bg-gray-500/20 text-gray-400 ring-gray-500/30",
};

export default function StatusBadge({ status, className = "" }: StatusBadgeProps) {
  const style = STYLES[status] ?? STYLES.closed;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ring-1 ring-inset capitalize ${style} ${className}`}
    >
      {status}
    </span>
  );
}
