"use client";

import type { ReactNode } from "react";

export type InfoHoverProps = {
  children: ReactNode;
  /** Eyebrow inside the panel (e.g. “Graph engine”). */
  heading?: string;
  /** Brutal technical disclosure — keep monospace-ish facts. */
  detail: ReactNode;
  className?: string;
};

/**
 * Progressive disclosure: primary UI stays clean; hover/focus reveals raw metrics.
 */
export function InfoHover({ children, heading, detail, className = "" }: InfoHoverProps) {
  return (
    <span
      className={`group relative inline-flex max-w-full align-baseline ${className}`}
      tabIndex={0}
    >
      <span className="cursor-help border-b border-dotted border-gray-500/90 text-inherit decoration-transparent hover:border-brand-400/80 hover:text-brand-100 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 focus-visible:rounded-sm">
        {children}
      </span>

      <span
        role="tooltip"
        data-testid="info-hover-panel"
        className="pointer-events-none absolute left-0 top-[calc(100%+8px)] z-[300] w-max max-w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-surface-600 bg-surface-950 px-3 py-2.5 text-left opacity-0 shadow-2xl shadow-black/50 ring-1 ring-white/5 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus:pointer-events-auto group-focus:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
      >
        {heading ? (
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500 mb-2">{heading}</p>
        ) : null}
        <div className="text-xs leading-snug">{detail}</div>
      </span>
    </span>
  );
}
