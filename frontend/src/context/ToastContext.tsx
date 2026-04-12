import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type Toast = { id: string; message: string; variant: "error" | "success" | "info" };

type ToastContextValue = {
  toasts: Toast[];
  toast: (message: string, variant?: Toast["variant"]) => void;
  dismiss: (id: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((message: string, variant: Toast["variant"] = "info") => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, message, variant }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 6000);
  }, []);

  const value = useMemo(() => ({ toasts, toast, dismiss }), [toasts, toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="fixed bottom-4 right-4 z-[250] flex flex-col gap-2 max-w-sm pointer-events-none"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto rounded-lg border px-4 py-3 text-sm shadow-lg ${
              t.variant === "error"
                ? "bg-red-950/95 border-red-500/40 text-red-100"
                : t.variant === "success"
                  ? "bg-emerald-950/95 border-emerald-500/40 text-emerald-100"
                  : "bg-surface-900 border-surface-600 text-gray-200"
            }`}
          >
            <div className="flex justify-between gap-3 items-start">
              <p>{t.message}</p>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="shrink-0 text-gray-500 hover:text-gray-300 text-lg leading-none"
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
