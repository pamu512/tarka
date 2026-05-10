import { AppSidebar } from "@/components/AppSidebar";
import { GlobalHeader } from "@/components/GlobalHeader";

type DashboardLayoutProps = {
  children: React.ReactNode;
};

export function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="flex min-h-dvh w-full min-w-0 flex-col bg-slate-950 text-slate-200">
      <GlobalHeader />
      <div className="flex min-h-0 min-w-0 flex-1">
        <AppSidebar />
        <main
          id="dashboard-main"
          className="flex min-h-0 min-w-0 flex-1 flex-col bg-slate-950"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
