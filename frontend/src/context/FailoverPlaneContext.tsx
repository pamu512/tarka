import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { integrations, type FailoverTogglesPayload, type FailoverTogglesState } from "../api/client";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 6000;

type FailoverPlaneContextValue = {
  loading: boolean;
  error: string | null;
  graphPlaneDisabled: boolean;
  aiPlaneDisabled: boolean;
  graphLatencyMsP95: number | null;
  aiLatencyMsP95: number | null;
  updatedAt: string | null;
  /** Pull latest from ingress (also runs on an interval when the tab is visible). */
  refresh: () => Promise<void>;
  /** Persist kill-switch state (integration-ingress / control plane). */
  setPlanes: (body: FailoverTogglesPayload) => Promise<void>;
};

const FailoverPlaneContext = createContext<FailoverPlaneContextValue | null>(null);

function mapState(r: FailoverTogglesState | null): Pick<
  FailoverPlaneContextValue,
  "graphPlaneDisabled" | "aiPlaneDisabled" | "graphLatencyMsP95" | "aiLatencyMsP95" | "updatedAt"
> {
  if (!r) {
    return {
      graphPlaneDisabled: false,
      aiPlaneDisabled: false,
      graphLatencyMsP95: null,
      aiLatencyMsP95: null,
      updatedAt: null,
    };
  }
  return {
    graphPlaneDisabled: Boolean(r.graph_plane_disabled),
    aiPlaneDisabled: Boolean(r.ai_plane_disabled),
    graphLatencyMsP95:
      typeof r.graph_latency_ms_p95 === "number" && Number.isFinite(r.graph_latency_ms_p95)
        ? r.graph_latency_ms_p95
        : null,
    aiLatencyMsP95:
      typeof r.ai_latency_ms_p95 === "number" && Number.isFinite(r.ai_latency_ms_p95) ? r.ai_latency_ms_p95 : null,
    updatedAt: typeof r.updated_at === "string" ? r.updated_at : null,
  };
}

export function FailoverPlaneProvider({ children }: { children: ReactNode }) {
  const [raw, setRaw] = useState<FailoverTogglesState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await integrations.failoverToggles();
      setRaw(r);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Failover toggles", action: "read plane state" }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const setPlanes = useCallback(async (body: FailoverTogglesPayload) => {
    const r = await integrations.setFailoverToggles(body);
    setRaw(r);
    setError(null);
  }, []);

  const mapped = useMemo(() => mapState(raw), [raw]);

  const value = useMemo(
    (): FailoverPlaneContextValue => ({
      loading,
      error,
      ...mapped,
      refresh,
      setPlanes,
    }),
    [loading, error, mapped, refresh, setPlanes],
  );

  return <FailoverPlaneContext.Provider value={value}>{children}</FailoverPlaneContext.Provider>;
}

export function useFailoverPlanes(): FailoverPlaneContextValue {
  const v = useContext(FailoverPlaneContext);
  if (!v) {
    throw new Error("useFailoverPlanes must be used within FailoverPlaneProvider");
  }
  return v;
}
