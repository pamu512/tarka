import { LiveTicker } from "@/components/live-ticker";

export default function HomePage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <LiveTicker />
    </div>
  );
}
