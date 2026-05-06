import { Component, type ErrorInfo, type ReactNode } from "react";

import { buildErrorTraceFromUnknown, mergeReactBoundaryFields, type GlobalErrorTrace } from "@/errors/buildErrorTrace";

import { GlobalErrorFallback } from "./GlobalErrorFallback";

type Props = { children: ReactNode };

type State = {
  trace: GlobalErrorTrace | null;
};

/**
 * Catches unhandled errors thrown during React render / lifecycle in the subtree.
 */
export class GlobalErrorBoundary extends Component<Props, State> {
  public state: State = { trace: null };

  public static getDerivedStateFromError(error: unknown): State {
    const base = buildErrorTraceFromUnknown(error, "react");
    return { trace: mergeReactBoundaryFields(base, error, undefined) };
  }

  public componentDidCatch(error: unknown, errorInfo: ErrorInfo): void {
    const base = buildErrorTraceFromUnknown(error, "react");
    this.setState({
      trace: mergeReactBoundaryFields(base, error, errorInfo.componentStack),
    });
  }

  private handleRetry = (): void => {
    this.setState({ trace: null });
  };

  public render(): ReactNode {
    const { trace } = this.state;
    if (trace) {
      return <GlobalErrorFallback trace={trace} onRetry={this.handleRetry} />;
    }
    return this.props.children;
  }
}
