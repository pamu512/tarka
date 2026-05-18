import { create } from "zustand";

import { decisionsApiBase } from "@/config/decisionsApi";
import type { RuntimeTier } from "@/state/runtimeEnvironmentStore";

export type MicroOnboardingPhase = "idle" | "loading" | "dashboard" | "first_run";

export type CheckRunState = "pending" | "running" | "ok" | "failed";

export interface OnboardingCheck {
  id: string;
  title: string;
  description: string;
  verify_path: string;
}

export interface OnboardingStatusBody {
  lifecycle_state: "uninitialized" | "ready";
  engine: string;
  analytics_store: string;
  checks: OnboardingCheck[];
}

interface MicroDevOnboardingState {
  phase: MicroOnboardingPhase;
  statusError: string | null;
  status: OnboardingStatusBody | null;
  /** Per-check HTTP outcome after explicit verification runs. */
  checkStates: Record<string, CheckRunState>;
  checkLastError: Record<string, string>;
  verifyInFlight: boolean;
  bootstrap: (tier: RuntimeTier) => Promise<void>;
  /** Sequentially GET each verify_path; only transitions to dashboard after status is `ready`. */
  runInfrastructureChecks: () => Promise<void>;
}

function joinUrl(base: string, path: string): string {
  const b = base.endsWith("/") ? base.slice(0, -1) : base;
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

async function fetchJson(url: string): Promise<{ ok: boolean; status: number; json: unknown }> {
  const res = await fetch(url, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store" });
  const text = await res.text();
  let json: unknown = null;
  if (text.trimStart().startsWith("{")) {
    try {
      json = JSON.parse(text) as unknown;
    } catch {
      json = { raw: text };
    }
  }
  return { ok: res.ok, status: res.status, json };
}

export const useMicroDevOnboardingStore = create<MicroDevOnboardingState>((set, get) => ({
  phase: "idle",
  statusError: null,
  status: null,
  checkStates: {},
  checkLastError: {},
  verifyInFlight: false,

  bootstrap: async (tier) => {
    if (tier !== "micro") {
      set({
        phase: "dashboard",
        statusError: null,
        status: null,
        checkStates: {},
        checkLastError: {},
        verifyInFlight: false,
      });
      return;
    }

    set({ phase: "loading", statusError: null });
    const base = decisionsApiBase();
    const url = joinUrl(base, "/v1/micro-dev/onboarding/status");
    try {
      const { ok, status, json } = await fetchJson(url);
      if (!ok) {
        set({
          phase: "first_run",
          statusError: `Onboarding status request failed (HTTP ${status}).`,
          status: null,
          checkStates: {},
          checkLastError: {},
        });
        return;
      }
      const body = json as OnboardingStatusBody;
      if (body.lifecycle_state === "ready" || body.checks.length === 0) {
        set({
          phase: "dashboard",
          status: body,
          statusError: null,
          checkStates: {},
          checkLastError: {},
        });
        return;
      }
      const initial: Record<string, CheckRunState> = {};
      for (const c of body.checks) {
        initial[c.id] = "pending";
      }
      set({
        phase: "first_run",
        status: body,
        statusError: null,
        checkStates: initial,
        checkLastError: {},
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({
        phase: "first_run",
        statusError: msg,
        status: null,
        checkStates: {},
        checkLastError: {},
      });
    }
  },

  runInfrastructureChecks: async () => {
    const { status } = get();
    if (!status?.checks.length) {
      return;
    }
    if (get().verifyInFlight) {
      return;
    }
    set({ verifyInFlight: true });
    const base = decisionsApiBase();
    const nextStates: Record<string, CheckRunState> = { ...get().checkStates };
    const nextErr: Record<string, string> = { ...get().checkLastError };

    try {
      for (const c of status.checks) {
        nextStates[c.id] = "running";
        nextErr[c.id] = "";
        set({ checkStates: { ...nextStates }, checkLastError: { ...nextErr } });

        const vurl = joinUrl(base, c.verify_path);
        const { ok, status: http, json } = await fetchJson(vurl);
        if (!ok || http !== 200) {
          const detail =
            json && typeof json === "object" && json !== null && "detail" in json
              ? JSON.stringify((json as { detail: unknown }).detail)
              : `HTTP ${http}`;
          nextStates[c.id] = "failed";
          nextErr[c.id] = detail;
          set({ checkStates: { ...nextStates }, checkLastError: { ...nextErr } });
          return;
        }
        nextStates[c.id] = "ok";
        set({ checkStates: { ...nextStates }, checkLastError: { ...nextErr } });
      }

      const statusUrl = joinUrl(base, "/v1/micro-dev/onboarding/status");
      const again = await fetchJson(statusUrl);
      if (again.ok && typeof again.json === "object" && again.json !== null) {
        const body = again.json as OnboardingStatusBody;
        if (body.lifecycle_state === "ready") {
          set({
            phase: "dashboard",
            status: body,
            statusError: null,
          });
          return;
        }
        set({
          status: body,
          statusError:
            "All checks returned HTTP 200, but the service still reports uninitialized. Use “Refresh status” after fixing the server.",
        });
        return;
      }
      set({ statusError: "Checks succeeded but status refresh failed." });
    } finally {
      set({ verifyInFlight: false });
    }
  },
}));
