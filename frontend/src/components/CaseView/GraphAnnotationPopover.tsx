import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type GraphAnnotationPopoverProps = {
  open: boolean;
  clientX: number;
  clientY: number;
  nodeId: string;
  initialText: string;
  onSave: (text: string) => void;
  onRemove: () => void;
  onClose: () => void;
};

/**
 * Small form anchored near the cursor for node annotations (right-click on graph).
 */
export function GraphAnnotationPopover({
  open,
  clientX,
  clientY,
  nodeId,
  initialText,
  onSave,
  onRemove,
  onClose,
}: GraphAnnotationPopoverProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [draft, setDraft] = useState(initialText);

  useEffect(() => {
    if (open) setDraft(initialText);
  }, [open, initialText, nodeId]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const el = panelRef.current;
      if (el && !el.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const panelW = 320;
  const panelH = 220;
  const left = Math.min(Math.max(8, clientX), vw - panelW - 8);
  const top = Math.min(Math.max(8, clientY), vh - panelH - 8);

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-hotkeys-ignore
      className="fixed z-[450] w-[min(22rem,calc(100vw-1rem))] rounded-xl border border-amber-500/35 bg-surface-950 shadow-2xl shadow-black/50 p-3 space-y-2"
      style={{ left, top }}
    >
      <div id={titleId} className="text-xs font-semibold text-amber-200/95 uppercase tracking-wide">
        Annotation layer
      </div>
      <p className="text-[11px] text-gray-500 font-mono truncate" title={nodeId}>
        Node: {nodeId}
      </p>
      <label className="block text-[11px] text-gray-400">
        Note (visible on hover + list)
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={4}
          className="mt-1 w-full rounded-lg border border-surface-600 bg-surface-900 px-2 py-1.5 text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-amber-500/50"
          placeholder='e.g. "Known good reseller account"'
          autoFocus
        />
      </label>
      <div className="flex flex-wrap gap-2 justify-end pt-1">
        <button
          type="button"
          onClick={onClose}
          className="px-2.5 py-1.5 text-xs rounded-lg border border-surface-600 text-gray-400 hover:bg-surface-800"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => onRemove()}
          className="px-2.5 py-1.5 text-xs rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-950/50"
        >
          Remove
        </button>
        <button
          type="button"
          onClick={() => onSave(draft)}
          className="px-2.5 py-1.5 text-xs rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-medium"
        >
          Save
        </button>
      </div>
    </div>,
    document.body,
  );
}
