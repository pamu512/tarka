import { useEffect, useState, type ReactElement, type ReactNode } from "react";

import { buildErrorTraceFromUnknown, type GlobalErrorTrace } from "@/errors/buildErrorTrace";

import { GlobalErrorBoundary } from "./GlobalErrorBoundary";
import { GlobalErrorFallback } from "./GlobalErrorFallback";

/**
 * Top-level shell: captures **unhandled promise rejections** (e.g. failed `fetch` / Axios without a
 * local `catch`) and delegates **React render errors** to {@link GlobalErrorBoundary}.
 */
export function GlobalErrorShell({ children }: { children: ReactNode }): ReactElement {
  const [asyncTrace, setAsyncTrace] = useState<GlobalErrorTrace | null>(null);

  useEffect(() => {
    const onRejection = (event: PromiseRejectionEvent) => {
      setAsyncTrace(buildErrorTraceFromUnknown(event.reason, "unhandledRejection"));
    };
    window.addEventListener("unhandledrejection", onRejection);
    return () => window.removeEventListener("unhandledrejection", onRejection);
  }, []);

  if (asyncTrace) {
    return (
      <GlobalErrorFallback
        trace={asyncTrace}
        onRetry={() => {
          setAsyncTrace(null);
        }}
      />
    );
  }

  return <GlobalErrorBoundary>{children}</GlobalErrorBoundary>;
}
