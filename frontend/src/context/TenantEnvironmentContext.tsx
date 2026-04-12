import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const TENANT_KEY = "tarka-workspace-tenant";
const ENV_KEY = "tarka-workspace-environment";

export type WorkspaceEnvironment = "sandbox" | "production";

type Value = {
  tenantId: string;
  setTenantId: (id: string) => void;
  environment: WorkspaceEnvironment;
  setEnvironment: (e: WorkspaceEnvironment) => void;
};

const Ctx = createContext<Value | null>(null);

function readTenant(): string {
  try {
    const s = localStorage.getItem(TENANT_KEY)?.trim();
    if (s) return s;
  } catch {
    /* ignore */
  }
  return "demo";
}

function readEnv(): WorkspaceEnvironment {
  try {
    const s = localStorage.getItem(ENV_KEY);
    if (s === "production" || s === "sandbox") return s;
  } catch {
    /* ignore */
  }
  return "sandbox";
}

export function TenantEnvironmentProvider({ children }: { children: ReactNode }) {
  const [tenantId, setTenantIdState] = useState(readTenant);
  const [environment, setEnvironmentState] = useState<WorkspaceEnvironment>(readEnv);

  const setTenantId = useCallback((id: string) => {
    const t = id.trim() || "demo";
    setTenantIdState(t);
    try {
      localStorage.setItem(TENANT_KEY, t);
    } catch {
      /* ignore */
    }
  }, []);

  const setEnvironment = useCallback((e: WorkspaceEnvironment) => {
    setEnvironmentState(e);
    try {
      localStorage.setItem(ENV_KEY, e);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(
    () => ({ tenantId, setTenantId, environment, setEnvironment }),
    [tenantId, setTenantId, environment, setEnvironment],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTenantEnvironment(): Value {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTenantEnvironment must be used within TenantEnvironmentProvider");
  return v;
}
