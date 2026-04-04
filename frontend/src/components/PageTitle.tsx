import type { ReactNode } from "react";
import { ModuleIcon, type ModuleId } from "./ModuleIcon";

export function PageTitle({
  module,
  children,
  className = "",
}: {
  module: ModuleId;
  children: ReactNode;
  className?: string;
}) {
  return (
    <h1
      className={`text-2xl font-bold text-gray-100 flex items-center gap-3 ${className}`.trim()}
    >
      <ModuleIcon module={module} className="w-8 h-8 text-brand-400" aria-hidden />
      {children}
    </h1>
  );
}
