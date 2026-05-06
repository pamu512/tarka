import { create } from "zustand";

import { purgeAllDataCaches } from "@/lib/dataCachesRegistry";

export type RuntimeTier = "micro" | "production";

export type RuntimeHealthStatus = "idle" | "loading" | "success" | "error";

const STORAGE_KEY = "tarka.runtime-tier";

function readPersistedTier(): RuntimeTier {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw === "micro" || raw === "production") {
      return raw;
    }
  } catch {
    /* sessionStorage may be unavailable */
  }
  return "micro";
}

function persistTier(tier: RuntimeTier): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, tier);
  } catch {
    /* ignore */
  }
}

/**
 * Resolves the health probe URL for the active tier. Reads `import.meta.env` on each call so
 * tests can adjust `VITE_HEALTH_URL_*` between cases without reloading modules.
 */
export function resolveRuntimeHealthUrl(tier: RuntimeTier): string {
  const micro = import.meta.env.VITE_HEALTH_URL_MICRO?.trim();
  const production = import.meta.env.VITE_HEALTH_URL_PRODUCTION?.trim();
  if (tier === "micro") {
    return micro || production || "/api/cases/v1/health";
  }
  return production || micro || "/api/cases/v1/health";
}

async function fetchRuntimeHealthSnapshot(tier: RuntimeTier): Promise<{
  ok: boolean;
  status: number;
  body: unknown;
}> {
  const url = resolveRuntimeHealthUrl(tier);
  const res = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const text = await res.text();
  let body: unknown = text;
  if (text.trimStart().startsWith("{") || text.trimStart().startsWith("[")) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  return { ok: res.ok, status: res.status, body };
}

export interface RuntimeEnvironmentState {
  tier: RuntimeTier;
  healthStatus: RuntimeHealthStatus;
  healthError: string | null;
  healthSnapshot: unknown | null;
  lastHealthHttpStatus: number | null;
  setRuntimeTier: (next: RuntimeTier) => Promise<void>;
  refreshRuntimeHealth: () => Promise<void>;
}

export const useRuntimeEnvironmentStore = create<RuntimeEnvironmentState>((set, get) => ({
  tier: readPersistedTier(),
  healthStatus: "idle",
  healthError: null,
  healthSnapshot: null,
  lastHealthHttpStatus: null,

  refreshRuntimeHealth: async () => {
    const tier = get().tier;
    set({ healthStatus: "loading", healthError: null });
    try {
      const { ok, status, body } = await fetchRuntimeHealthSnapshot(tier);
      set({ lastHealthHttpStatus: status });
      if (!ok) {
        set({
          healthStatus: "error",
          healthError: `Health check failed with HTTP ${status}`,
          healthSnapshot: body,
        });
        return;
      }
      set({
        healthStatus: "success",
        healthError: null,
        healthSnapshot: body,
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      set({
        healthStatus: "error",
        healthError: message,
        healthSnapshot: null,
        lastHealthHttpStatus: null,
      });
    }
  },

  setRuntimeTier: async (next) => {
    const prev = get().tier;
    if (prev === next) {
      return;
    }
    await purgeAllDataCaches();
    set({ tier: next });
    persistTier(next);
    await get().refreshRuntimeHealth();
  },
}));

/** Test harness / HMR: reset persisted tier and in-memory health fields without touching caches. */
export function resetRuntimeEnvironmentStoreForTests(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  useRuntimeEnvironmentStore.setState({
    tier: "micro",
    healthStatus: "idle",
    healthError: null,
    healthSnapshot: null,
    lastHealthHttpStatus: null,
  });
}
