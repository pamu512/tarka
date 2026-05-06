import { decisionsApiBase } from "@/config/decisionsApi";
import { useMicroDevOnboardingStore, type CheckRunState } from "@/state/microDevOnboardingStore";
import { useRuntimeEnvironmentStore } from "@/state/runtimeEnvironmentStore";

function stateLabel(s: CheckRunState): string {
  switch (s) {
    case "pending":
      return "Awaiting verification";
    case "running":
      return "Calling health endpoint…";
    case "ok":
      return "HTTP 200 OK";
    case "failed":
      return "Failed";
    default:
      return s;
  }
}

export function MicroDevFirstRunWizard() {
  const status = useMicroDevOnboardingStore((s) => s.status);
  const statusError = useMicroDevOnboardingStore((s) => s.statusError);
  const checkStates = useMicroDevOnboardingStore((s) => s.checkStates);
  const checkLastError = useMicroDevOnboardingStore((s) => s.checkLastError);
  const verifyInFlight = useMicroDevOnboardingStore((s) => s.verifyInFlight);
  const phase = useMicroDevOnboardingStore((s) => s.phase);
  const runInfrastructureChecks = useMicroDevOnboardingStore((s) => s.runInfrastructureChecks);
  const bootstrap = useMicroDevOnboardingStore((s) => s.bootstrap);
  const tier = useRuntimeEnvironmentStore((s) => s.tier);

  const checks = status?.checks ?? [];

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-surface-950 text-gray-100">
      <header className="border-b border-surface-800 px-8 py-6">
        <h1 className="text-xl font-semibold tracking-tight text-white">First run — local infrastructure</h1>
        <p className="mt-2 max-w-3xl text-sm text-gray-400 leading-relaxed">
          Micro tier requires a writable SQLite audit file and a working DuckDB analytics binding when{" "}
          <code className="text-gray-300">TARKA_ANALYTICS_STORE</code> targets DuckDB. The main dashboard stays
          disabled until every required check below has returned <span className="text-emerald-400">HTTP 200</span>{" "}
          from the decision API.
        </p>
        <p className="mt-2 text-xs text-gray-600">
          API base: <code className="text-gray-400">{decisionsApiBase()}</code>
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-8 py-8">
        {statusError && !checks.length ? (
          <div
            className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
            role="alert"
          >
            {statusError}
          </div>
        ) : null}

        {checks.length ? (
          <ol className="max-w-2xl space-y-4">
            {checks.map((c, idx) => {
              const st = checkStates[c.id] ?? "pending";
              const err = checkLastError[c.id];
              return (
                <li
                  key={c.id}
                  className="rounded-xl border border-surface-700 bg-surface-900/80 p-5 shadow-sm"
                >
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-800 text-xs font-bold text-gray-400">
                      {idx + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-white">{c.title}</h2>
                      <p className="mt-1 text-xs text-gray-500 leading-relaxed">{c.description}</p>
                      <p className="mt-2 font-mono text-[11px] text-gray-600 break-all">
                        GET {decisionsApiBase()}
                        {c.verify_path}
                      </p>
                      <p className="mt-2 text-xs">
                        <span
                          className={
                            st === "ok"
                              ? "text-emerald-400"
                              : st === "failed"
                                ? "text-rose-400"
                                : st === "running"
                                  ? "text-amber-300"
                                  : "text-gray-500"
                          }
                        >
                          {stateLabel(st)}
                        </span>
                      </p>
                      {err ? (
                        <pre className="mt-2 max-h-32 overflow-auto rounded bg-black/40 p-2 text-[11px] text-rose-200">
                          {err}
                        </pre>
                      ) : null}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : phase === "first_run" && !statusError ? (
          <p className="text-sm text-gray-500">No onboarding checks are required for this configuration.</p>
        ) : null}

        {statusError && checks.length ? (
          <p className="mt-6 max-w-2xl text-sm text-amber-200/90" role="status">
            {statusError}
          </p>
        ) : null}
      </div>

      <footer className="border-t border-surface-800 px-8 py-5 flex flex-wrap items-center gap-3 bg-surface-900/90">
        <button
          type="button"
          className="rounded-lg border border-surface-600 bg-surface-800 px-4 py-2.5 text-sm font-medium text-gray-200 hover:bg-surface-700 disabled:opacity-50"
          disabled={verifyInFlight}
          onClick={() => void bootstrap(tier)}
        >
          Refresh status
        </button>
        <button
          type="button"
          className="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-500 disabled:opacity-50 disabled:pointer-events-none"
          disabled={verifyInFlight || !checks.length}
          onClick={() => void runInfrastructureChecks()}
        >
          {verifyInFlight ? "Running checks…" : "Run infrastructure checks"}
        </button>
        <p className="text-xs text-gray-600">
          Bypass is not available. Resolve filesystem permissions and Python bindings, then re-run checks until the
          service reports <code className="text-gray-400">lifecycle_state: ready</code>.
        </p>
      </footer>
    </div>
  );
}
