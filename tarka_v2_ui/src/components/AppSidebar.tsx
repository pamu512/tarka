"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Archive, HeartPulse } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Live Ingestion", icon: Activity },
  { href: "/audit-vault", label: "Audit Vault", icon: Archive },
  { href: "/system-health", label: "System Health", icon: HeartPulse },
] as const;

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="flex h-full min-h-0 w-60 shrink-0 flex-col border-r border-slate-800/90 bg-slate-950"
      aria-label="Primary"
    >
      <div className="flex h-14 shrink-0 items-center border-b border-slate-800/90 px-4">
        <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Tarka-UI
        </span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/"
              ? pathname === "/"
              : pathname === href || pathname.startsWith(`${href}/`);

          return (
            <Link
              key={href}
              href={href}
              className={[
                "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
                active
                  ? "bg-slate-900 text-slate-100 ring-1 ring-slate-700/80"
                  : "text-slate-400 hover:bg-slate-900/60 hover:text-slate-200",
              ].join(" ")}
            >
              <Icon
                className="size-4 shrink-0 opacity-80"
                aria-hidden
                strokeWidth={1.75}
              />
              <span className="truncate">{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
