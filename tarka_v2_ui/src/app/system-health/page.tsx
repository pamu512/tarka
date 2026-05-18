import { HealthGrid } from "@/components/health";

export default function SystemHealthPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <HealthGrid />
    </div>
  );
}
