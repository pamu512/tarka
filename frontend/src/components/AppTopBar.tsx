import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { ModuleIcon } from "./ModuleIcon";

function IconUser({ className = "w-5 h-5" }: { className?: string }) {
  return (
    <svg
      className={`shrink-0 ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20.5c1.8-4 12.2-4 14 0" />
    </svg>
  );
}

const iconBtn =
  "relative flex h-10 w-10 items-center justify-center rounded-xl text-gray-500 hover:text-gray-200 hover:bg-surface-800/90 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50";

function NotificationNavLink({ actionableCount }: { actionableCount: number }) {
  const show = actionableCount > 0;
  const label = show
    ? `Notifications, ${actionableCount} need attention`
    : "Notifications";
  const shown = actionableCount > 99 ? "99+" : String(actionableCount);

  return (
    <NavLink
      to="/notifications"
      className={({ isActive }) =>
        `${iconBtn} ${isActive ? "text-brand-400 bg-brand-600/15 hover:bg-brand-600/20" : ""}`
      }
      aria-label={label}
      title={label}
    >
      <ModuleIcon module="notifications" className="w-[1.25rem] h-[1.25rem]" aria-hidden />
      {show ? (
        <span
          className="absolute -right-0.5 -top-0.5 flex h-[1.125rem] min-w-[1.125rem] items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-bold tabular-nums text-black ring-2 ring-white dark:ring-surface-950"
          aria-hidden
        >
          {shown}
        </span>
      ) : null}
    </NavLink>
  );
}

function AccountMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className={`${iconBtn} ${open ? "text-gray-200 bg-surface-800" : ""}`}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Account menu"
        onClick={() => setOpen((v) => !v)}
      >
        <IconUser className="w-[1.25rem] h-[1.25rem]" />
      </button>
      {open ? (
        <div
          className="absolute right-0 z-50 mt-1.5 w-56 rounded-xl border border-surface-700 bg-surface-900 py-1 shadow-xl shadow-black/40"
          role="menu"
        >
          <div className="border-b border-surface-700 px-3 py-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">Signed in</div>
            <div className="mt-0.5 text-sm font-medium text-gray-100">Demo operator</div>
            <div className="text-xs text-gray-500">demo@tarka.local</div>
          </div>
          <NavLink
            to="/settings"
            role="menuitem"
            className="block px-3 py-2.5 text-sm text-gray-300 hover:bg-surface-800"
            onClick={() => setOpen(false)}
          >
            Settings &amp; appearance
          </NavLink>
          <button
            type="button"
            role="menuitem"
            className="w-full px-3 py-2.5 text-left text-sm text-gray-500 cursor-not-allowed"
            disabled
          >
            Sign out (soon)
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function AppTopBar({ notificationActionableCount }: { notificationActionableCount: number }) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-end gap-0.5 border-b border-surface-700 bg-surface-900/95 px-3 backdrop-blur-sm sm:px-4">
      <NavLink
        to="/help"
        className={({ isActive }) =>
          `${iconBtn} ${isActive ? "text-brand-400 bg-brand-600/15 hover:bg-brand-600/20" : ""}`
        }
        aria-label="Help and guide"
        title="Help"
      >
        <ModuleIcon module="help" className="w-[1.25rem] h-[1.25rem]" aria-hidden />
      </NavLink>
      <NotificationNavLink actionableCount={notificationActionableCount} />
      <NavLink
        to="/settings"
        className={({ isActive }) =>
          `${iconBtn} ${isActive ? "text-brand-400 bg-brand-600/15 hover:bg-brand-600/20" : ""}`
        }
        aria-label="Settings"
        title="Settings"
      >
        <ModuleIcon module="settings" className="w-[1.25rem] h-[1.25rem]" aria-hidden />
      </NavLink>
      <AccountMenu />
    </header>
  );
}
